import AppKit
import WebKit

// 独立 Bundle 的登录兼容性验证，不链接生产服务或读取浏览器/Codex 凭据。
final class Probe: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate, WKScriptMessageHandler {
    let arguments = CommandLine.arguments
    var window: NSWindow!
    var web: WKWebView!
    var popups: [NSWindow] = []
    let status = NSTextField(labelWithString: "等待登录")
    let output = NSTextView()
    var readButton: NSButton!
    var generation = 0
    var collecting = false
    var testCompleted = false
    var testStarted = false
    var expectedIdentity: String?
    let diagnostics = ProbeDiagnostics()
    var showingDiagnostics = true
    var diagnosticWrite: DispatchWorkItem?
    var probeBuild: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown" }
    var diagnoseAuth: Bool { arguments.contains("--diagnose-auth") }
    var automated: Bool { testURL != nil || diagnoseAuth }
    let hosts: Set<String> = [
        "chatgpt.com", "auth.openai.com", "auth0.openai.com", "auth.chatgpt.com",
        "accounts.google.com", "appleid.apple.com", "login.microsoftonline.com",
        "login.live.com", "challenges.cloudflare.com"
    ]
    var testURL: URL? {
        guard let raw = option("--self-test"), let url = URL(string: raw),
              url.scheme == "http", url.host == "127.0.0.1", url.port != nil else { return nil }
        return url
    }
    var origin: String {
        if let url = testURL { return "http://127.0.0.1:\(url.port!)" }
        return "https://chatgpt.com"
    }
    var resultURL: URL {
        if automated, let path = option("--result") { return URL(fileURLWithPath: path) }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Token BI WKWebView Probe/latest-result.json")
    }

    func option(_ name: String) -> String? {
        guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else { return nil }
        return arguments[index + 1]
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if arguments.contains("--self-test") && testURL == nil { exit(2) }
        if diagnoseAuth && option("--result") == nil { exit(2) }
        expectedIdentity = testURL == nil ? UserDefaults.standard.string(forKey: "identityKey") : option("--expected-identity")
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出验证", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = automated ? .nonPersistent() : .default()
        if testURL != nil, let raw = option("--test-profile"), let uuid = UUID(uuidString: raw) {
            if #available(macOS 14.0, *) { configuration.websiteDataStore = WKWebsiteDataStore(forIdentifier: uuid) }
        }
        if let path = Bundle.main.url(forResource: "diagnostics", withExtension: "js"),
           let script = try? String(contentsOf: path, encoding: .utf8) {
            configuration.userContentController.add(self, name: "probeDiagnostics")
            configuration.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        }
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        web.uiDelegate = self

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1060, height: 760),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Token BI · WKWebView 验证"
        window.minSize = NSSize(width: 760, height: 560)
        window.delegate = self
        window.isReleasedWhenClosed = false
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 8
        root.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)
        let toolbar = NSStackView()
        toolbar.spacing = 8
        toolbar.addArrangedSubview(button("登录", symbol: "person.crop.circle", action: #selector(login)))
        toolbar.addArrangedSubview(button("额度网页", symbol: "chart.bar", action: #selector(usagePage)))
        readButton = button("读取额度", symbol: "arrow.clockwise", action: #selector(collect))
        toolbar.addArrangedSubview(readButton)
        toolbar.addArrangedSubview(button("诊断", symbol: "stethoscope", action: #selector(showDiagnostics)))
        toolbar.addArrangedSubview(button("清除验证会话", symbol: "trash", action: #selector(clearSession)))
        root.addArrangedSubview(toolbar)
        status.font = NSFont.systemFont(ofSize: 12)
        status.lineBreakMode = .byTruncatingMiddle
        root.addArrangedSubview(status)
        root.addArrangedSubview(web)
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        output.isEditable = false
        output.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        output.isVerticallyResizable = true
        output.isHorizontallyResizable = false
        output.textContainer?.widthTracksTextView = true
        output.autoresizingMask = [.width]
        scroll.documentView = output
        root.addArrangedSubview(scroll)
        window.contentView = root
        let items: [NSView] = [toolbar, status, web, scroll]
        for item in items {
            item.translatesAutoresizingMaskIntoConstraints = false
            item.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -24).isActive = true
        }
        scroll.heightAnchor.constraint(equalToConstant: 150).isActive = true
        web.heightAnchor.constraint(greaterThanOrEqualToConstant: 300).isActive = true
        root.setHuggingPriority(.defaultLow, for: .vertical)
        window.center()
        if !automated {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
        diagnostics.changed = { [weak self] in self?.diagnosticsChanged() }
        if diagnoseAuth {
            navigate("https://auth.openai.com/log-in")
            DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
                self?.finish(["category": "navigation_trace", "schema": 1])
            }
        } else if let url = testURL {
            web.load(URLRequest(url: url))
            DispatchQueue.main.asyncAfter(deadline: .now() + 35) { [weak self] in
                guard let self, !self.testCompleted else { return }
                self.finish(["category": "native_deadline", "schema": 1])
            }
        } else { login() }
    }

    func button(_ title: String, symbol: String, action: Selector) -> NSButton {
        let item = NSButton(title: title, target: self, action: action)
        item.bezelStyle = .rounded
        item.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)
        item.imagePosition = .imageLeading
        item.toolTip = title
        return item
    }

    @objc func login() { navigate("https://chatgpt.com/auth/login") }
    @objc func usagePage() { navigate("https://chatgpt.com/codex/cloud/settings/analytics#usage") }
    func navigate(_ address: String) {
        invalidate()
        web.load(URLRequest(url: URL(string: address)!))
    }
    func invalidate() {
        generation += 1
        collecting = false
        readButton?.isEnabled = true
    }
    func canCollect(_ url: URL?) -> Bool {
        guard let url else { return false }
        if let test = testURL { return url.scheme == test.scheme && url.host == test.host && url.port == test.port }
        return url.scheme == "https" && url.host == "chatgpt.com" && (url.port == nil || url.port == 443)
    }
    func allowed(_ url: URL?) -> Bool {
        guard let url else { return false }
        if testURL != nil { return canCollect(url) }
        if url.absoluteString == "about:blank" { return true }
        return url.scheme == "https" && hosts.contains(url.host ?? "") && (url.port == nil || url.port == 443)
    }
    static func allowedAuthFrame(_ target: URL?, source: URL?, isMainFrame: Bool) -> Bool {
        // Sentinel 是官方认证子页面，不开放为顶层导航或任意第三方的跳转目标。
        guard !isMainFrame, let target, let source else { return false }
        let sources: Set<String> = ["chatgpt.com", "auth.openai.com", "auth0.openai.com", "auth.chatgpt.com", "sentinel.openai.com"]
        return target.scheme == "https" && target.host == "sentinel.openai.com"
            && (target.port == nil || target.port == 443)
            && target.user == nil && target.password == nil
            && source.scheme == "https" && sources.contains(source.host ?? "")
            && (source.port == nil || source.port == 443)
    }

    func record(_ event: String, url: URL?, fields: [String: Any] = [:]) {
        diagnostics.record(event, fields: ProbeDiagnostics.endpoint(url).merging(fields) { _, new in new })
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard allowed(message.frameInfo.request.url),
              let body = message.body as? [String: Any], let event = body["event"] as? String else { return }
        diagnostics.record(event, fields: body.merging(["main_frame": message.frameInfo.isMainFrame]) { _, new in new })
        // 网页遥测、取消请求和子资源异常只记诊断，不覆盖导航或主动读取的结果。
    }
    @objc func showDiagnostics() {
        showingDiagnostics = true
        renderDiagnostics()
    }
    func renderDiagnostics() {
        let value: [String: Any] = ["probe_build": probeBuild, "events": diagnostics.rows]
        if let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
           let text = String(data: data, encoding: .utf8) {
            output.string = text
            output.scrollToEndOfDocument(nil)
        }
    }
    func diagnosticsChanged() {
        if showingDiagnostics { renderDiagnostics() }
        guard !automated else { return }
        diagnosticWrite?.cancel()
        let write = DispatchWorkItem { [weak self] in self?.saveDiagnostics() }
        diagnosticWrite = write
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: write)
    }
    func saveDiagnostics() {
        let path = resultURL.deletingLastPathComponent().appendingPathComponent("latest-diagnostics.json")
        let value: [String: Any] = ["probe_build": probeBuild, "events": diagnostics.rows]
        do {
            let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
            try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try data.write(to: path, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        } catch { status.stringValue = "诊断文件写入失败" }
    }

    @objc func collect() {
        guard !collecting else { return }
        guard canCollect(web.url) else {
            finish(["category": "origin_rejected", "schema": 1]); return
        }
        guard let path = Bundle.main.url(forResource: "collect", withExtension: "js"),
              let script = try? String(contentsOf: path, encoding: .utf8) else {
            finish(["category": "resource_missing", "schema": 1]); return
        }
        generation += 1
        let request = generation
        collecting = true
        readButton.isEnabled = false
        status.stringValue = "读取中"
        web.callAsyncJavaScript(script, arguments: ["options": ["origin": origin, "timeoutMs": testURL == nil ? 5000 : 400]],
                                in: nil, in: .defaultClient) { [weak self] response in
            guard let self, request == self.generation else { return }
            self.collecting = false
            self.readButton.isEnabled = true
            guard self.canCollect(self.web.url) else { return }
            switch response {
            case .success(let value):
                guard let result = value as? [String: Any] else {
                    self.finish(["category": "invalid_result", "schema": 1]); return
                }
                self.finish(result)
            case .failure(let error):
                self.finish(["category": "javascript_error", "schema": 1, "error_code": (error as NSError).code])
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 24) { [weak self] in
            guard let self, request == self.generation, self.collecting else { return }
            self.invalidate()
            self.finish(["category": "native_deadline", "schema": 1])
        }
    }

    func finish(_ value: [String: Any]) {
        if automated && testCompleted { return }
        var result = value
        if result["category"] as? String == "success",
           let identity = result["identity"] as? [String: Any], let key = identity["key"] as? String {
            if let expectedIdentity, key != expectedIdentity {
                result["category"] = "account_mismatch"
                result.removeValue(forKey: "usage")
            } else if testURL == nil {
                expectedIdentity = key
                UserDefaults.standard.set(key, forKey: "identityKey")
            }
        }
        result["engine"] = "WKWebView"
        result["os"] = ProcessInfo.processInfo.operatingSystemVersionString
        result["probe_build"] = probeBuild
        result["diagnostics"] = diagnostics.rows
        showingDiagnostics = false
        let labels = [
            "success": "读取成功", "auth_required": "需要登录", "access_denied": "访问被拒绝，请查看网页提示",
            "challenge": "需要在网页完成人机验证", "rate_limited": "请求受限，请稍后再试",
            "network_error": "网络或服务器异常", "timeout": "请求超时", "native_deadline": "读取超时",
            "schema_changed": "未识别到额度 JSON", "identity_unknown": "无法确认账号，未采纳额度",
            "identity_changed": "读取期间账号变化，已丢弃结果", "account_mismatch": "账号与上次不同，未采纳额度",
            "origin_rejected": "请先返回 ChatGPT 页面", "dom_candidate": "仅发现 DOM 候选，尚未完成语义验收"
        ]
        let category = result["category"] as? String ?? "unknown"
        status.stringValue = labels[category] ?? category
        do {
            let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            output.string = String(data: data, encoding: .utf8) ?? ""
            try FileManager.default.createDirectory(at: resultURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try data.write(to: resultURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: resultURL.path)
        } catch { status.stringValue = "诊断文件写入失败" }
        if automated {
            testCompleted = true
            if let path = option("--screenshot") {
                web.takeSnapshot(with: nil) { picture, _ in
                    if let tiff = picture?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
                       let png = bitmap.representation(using: .png, properties: [:]) {
                        try? png.write(to: URL(fileURLWithPath: path))
                    }
                    NSApp.terminate(nil)
                }
            } else { NSApp.terminate(nil) }
        }
    }

    @objc func clearSession() {
        guard testURL == nil else { return }
        let alert = NSAlert()
        alert.messageText = "清除本验证 App 的登录会话？"
        alert.informativeText = "不会修改 Codex、正式 Token BI 或其他浏览器的登录信息。"
        alert.addButton(withTitle: "取消")
        alert.addButton(withTitle: "清除")
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        invalidate()
        expectedIdentity = nil
        UserDefaults.standard.removeObject(forKey: "identityKey")
        for popup in popups { popup.close() }
        popups.removeAll()
        web.stopLoading()
        web.configuration.websiteDataStore.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast) { [weak self] in
            self?.login()
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let authFrame = testURL == nil && Self.allowedAuthFrame(action.request.url, source: action.sourceFrame.request.url,
                                                               isMainFrame: action.targetFrame?.isMainFrame ?? true)
        guard allowed(action.request.url) || authFrame else {
            record("navigation_blocked", url: action.request.url, fields: ["main_frame": action.targetFrame?.isMainFrame ?? false])
            if action.targetFrame?.isMainFrame != false { status.stringValue = "已阻止非验证范围的页面跳转" }
            decisionHandler(.cancel)
            if testURL != nil { finish(["category": "navigation_blocked", "schema": 1]) }
            return
        }
        record("navigation_allowed", url: action.request.url, fields: ["main_frame": action.targetFrame?.isMainFrame ?? false])
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        var fields: [String: Any] = ["main_frame": response.isForMainFrame]
        if let http = response.response as? HTTPURLResponse { fields["status"] = http.statusCode }
        record("navigation_response", url: response.response.url, fields: fields)
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if webView === web {
            invalidate()
            status.stringValue = "加载中 · \(webView.url?.host ?? "")"
        }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === web else { return }
        status.stringValue = "\(webView.url?.host ?? "") · 页面就绪"
        if testURL != nil && !testStarted {
            testStarted = true
            let delay = Double(option("--collect-delay") ?? "0") ?? 0
            DispatchQueue.main.asyncAfter(deadline: .now() + min(max(delay, 0), 3)) { [weak self] in self?.collect() }
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        record("navigation_failed", url: webView.url, fields: ["error_code": (error as NSError).code])
        invalidate()
        status.stringValue = "网页加载失败（\((error as NSError).code)）"
        if testURL != nil { finish(["category": "navigation_error", "schema": 1, "error_code": (error as NSError).code]) }
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        self.webView(webView, didFailProvisionalNavigation: navigation, withError: error)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        record("web_process_terminated", url: webView.url)
        invalidate()
        finish(["category": "web_process_terminated", "schema": 1])
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard allowed(action.request.url), testURL == nil else {
            record("popup_blocked", url: action.request.url)
            return nil
        }
        record("popup_opened", url: action.request.url)
        let child = WKWebView(frame: .zero, configuration: configuration)
        child.navigationDelegate = self
        child.uiDelegate = self
        let popup = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 700),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        popup.title = "Token BI · 登录"
        popup.isReleasedWhenClosed = false
        popup.contentView = child
        popups.append(popup)
        popup.center()
        popup.makeKeyAndOrderFront(nil)
        return child
    }
    func webViewDidClose(_ webView: WKWebView) {
        popups.first(where: { $0.contentView === webView })?.close()
        popups.removeAll(where: { $0.contentView === webView })
    }
    func presentDialog(_ webView: WKWebView, frame: WKFrameInfo, message: String,
                       kind: String, defaultText: String? = nil, completion: @escaping (Bool, String?) -> Void) {
        record("dialog_\(kind)", url: frame.request.url)
        guard allowed(frame.request.url), let parent = webView.window, testURL == nil else {
            completion(false, nil); return
        }
        let alert = NSAlert()
        alert.messageText = "网页提示 · \(frame.request.url?.host ?? "")"
        alert.informativeText = String(message.prefix(8000))
        alert.addButton(withTitle: "确定")
        if kind != "alert" { alert.addButton(withTitle: "取消") }
        let input = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        if kind == "prompt" {
            input.stringValue = defaultText ?? ""
            alert.accessoryView = input
        }
        alert.beginSheetModal(for: parent) { response in
            completion(response == .alertFirstButtonReturn, kind == "prompt" ? input.stringValue : nil)
        }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        presentDialog(webView, frame: frame, message: message, kind: "alert") { _, _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        presentDialog(webView, frame: frame, message: message, kind: "confirm") { accepted, _ in completionHandler(accepted) }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        presentDialog(webView, frame: frame, message: prompt, kind: "prompt", defaultText: defaultText) { accepted, text in
            completionHandler(accepted ? text : nil)
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        if !automated { diagnosticWrite?.cancel(); saveDiagnostics() }
    }
}

@main
enum ProbeMain {
    static func main() {
        let arguments = CommandLine.arguments
        if arguments.contains("--check-auth-frame-policy") {
            guard arguments.count == 5 else { exit(2) }
            let allowed = Probe.allowedAuthFrame(URL(string: arguments[2]), source: URL(string: arguments[3]),
                                                 isMainFrame: arguments[4] != "subframe")
            print(allowed ? "allowed" : "blocked")
            return
        }
        let app = NSApplication.shared
        app.setActivationPolicy(CommandLine.arguments.contains("--self-test") || CommandLine.arguments.contains("--diagnose-auth") ? .prohibited : .regular)
        let delegate = Probe()
        app.delegate = delegate
        app.run()
    }
}
