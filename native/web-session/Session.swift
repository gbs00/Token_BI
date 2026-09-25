import AppKit
import WebKit
import Network

// 仅通过父进程的匿名管道接收命令；远程网页没有本地 IPC 或文件权限。
final class WebSession: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    var web: WKWebView?
    var window: NSWindow?
    var popups: [NSWindow] = []
    let status = NSTextField(labelWithString: "等待登录")
    var state = "stopped"
    var generation = 0
    var reading = false
    var evaluating = false
    var pending: [String] = []
    var autoRead = false
    var loginActive = false
    var expectedIdentity: String?
    var processFailures = 0
    var lastProcessFailure = Date.distantPast
    var fallbackNavigation = false
    var loginAttempts = 0
    var loginRedirected = false
    var testURL: URL?
    var origin = "https://chatgpt.com"
    var dataStore = WKWebsiteDataStore.default()
    let home = "https://chatgpt.com/"
    let usage = "https://chatgpt.com/codex/cloud/settings/analytics#usage"
    let network = NWPathMonitor()
    var online: Bool?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "--fixture"), index + 1 < args.count {
            guard let url = URL(string: args[index + 1]), url.scheme == "http", url.host == "127.0.0.1",
                  let port = url.port, url.user == nil, url.password == nil else { exit(2) }
            testURL = url
            origin = "http://127.0.0.1:\(port)"
            dataStore = .nonPersistent()
        }
        if let index = args.firstIndex(of: "--profile"), index + 1 < args.count,
           let id = UUID(uuidString: args[index + 1]) {
            if #available(macOS 14.0, *) { dataStore = WKWebsiteDataStore(forIdentifier: id) }
        }
        installMenu()
        network.pathUpdateHandler = { [weak self] path in
            DispatchQueue.main.async {
                guard let self else { return }
                let available = path.status == .satisfied
                if self.online != available {
                    self.online = available
                    self.send(["event": available ? "network_online" : "network_offline"])
                }
            }
        }
        network.start(queue: DispatchQueue.global(qos: .utility))
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification,
            object: nil, queue: .main) { [weak self] _ in self?.send(["event": "wake"]) }
        // EOF 表示拥有者退出，组件随即退出，不留下网页登录孤儿进程。
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var buffer = Data()
            while true {
                let chunk = FileHandle.standardInput.availableData
                if chunk.isEmpty { DispatchQueue.main.async { NSApp.terminate(nil) }; return }
                buffer.append(chunk)
                if buffer.count > 16384 { DispatchQueue.main.async { NSApp.terminate(nil) }; return }
                while let end = buffer.firstIndex(of: 10) {
                    let line = Data(buffer[..<end])
                    buffer.removeSubrange(...end)
                    guard let command = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
                    DispatchQueue.main.async { self?.handle(command) }
                }
            }
        }
        send(["event": "ready", "protocol": 1])
    }

    func send(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value), data.count < 131072 else { return }
        FileHandle.standardOutput.write(data + Data([10]))
    }
    func reply(_ id: String, _ value: [String: Any]) { send(["id": id, "result": value]) }
    func snapshot() -> [String: Any] {
        ["state": state, "visible": loginActive, "engine": "WKWebView"]
    }
    func handle(_ command: [String: Any]) {
        guard let id = command["id"] as? String, !id.isEmpty, id.count <= 80,
              let method = command["method"] as? String else { return }
        let key = command["expected_identity"] as? String
        if let key, key.range(of: "^[a-f0-9]{64}$", options: .regularExpression) == nil {
            reply(id, ["category": "invalid_request"]); return
        }
        switch method {
        case "status": reply(id, snapshot())
        case "login":
            cancelRead()
            expectedIdentity = key
            loginActive = true
            loginAttempts = 0
            loginRedirected = false
            state = "awaiting_login"
            ensureWeb()
            showWindow()
            if web?.url == nil { loginRedirected = true; load(testURL?.absoluteString ?? "https://chatgpt.com/auth/login") }
            else if canCollect(web?.url), web?.isLoading == false { startRead(id: nil) }
            reply(id, snapshot())
        case "collect":
            if (!pending.isEmpty || reading) && key != expectedIdentity {
                reply(id, ["category": "account_mismatch"]); return
            }
            expectedIdentity = key
            startRead(id: id)
        case "hide":
            hideWindow()
            reply(id, snapshot())
        case "shutdown":
            cancelRead()
            reply(id, ["state": "stopped"])
            NSApp.terminate(nil)
        default: reply(id, ["category": "invalid_request"])
        }
    }
    func ensureWeb() {
        guard web == nil else { return }
        let config = WKWebViewConfiguration()
        config.websiteDataStore = dataStore
        let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 960, height: 640), configuration: config)
        view.navigationDelegate = self
        view.uiDelegate = self
        web = view
        window?.contentView = makeContent(view)
    }
    func canCollect(_ url: URL?) -> Bool {
        guard let url else { return false }
        if let testURL { return url.scheme == "http" && url.host == testURL.host && url.port == testURL.port }
        return NavigationPolicy.secure(url) && url.host == "chatgpt.com"
    }
    func allowed(_ url: URL?, source: URL? = nil, main: Bool = true) -> Bool {
        if testURL != nil { return canCollect(url) || url?.absoluteString == "about:blank" }
        return NavigationPolicy.allowed(url, source: source, main: main)
    }
    func load(_ value: String) { if let url = URL(string: value) { web?.load(URLRequest(url: url)) } }
    func startRead(id: String?) {
        if let id { pending.append(id) } else { autoRead = true }
        guard !reading else { return }
        if testURL == nil && online == false { finish(["category": "offline"]); return }
        if processFailures >= 2 && Date().timeIntervalSince(lastProcessFailure) < 60 {
            finish(["category": "web_process_terminated"]); return
        }
        generation += 1
        let epoch = generation
        reading = true
        fallbackNavigation = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 24) { [weak self] in
            guard let self, self.generation == epoch, self.reading else { return }
            self.finish(["category": "timeout"])
        }
        ensureWeb()
        guard let web else { finish(["category": "internal_error"]); return }
        if web.url == nil { load(testURL?.absoluteString ?? home); return }
        if web.isLoading { return }
        if !canCollect(web.url) { finish(["category": "auth_required"]); return }
        collect(epoch)
    }
    func collect(_ epoch: Int) {
        guard reading, !evaluating, generation == epoch, let web, canCollect(web.url) else { return }
        guard let path = Bundle.main.url(forResource: "collect", withExtension: "js"),
              let script = try? String(contentsOf: path, encoding: .utf8) else {
            finish(["category": "internal_error"]); return
        }
        var options: [String: Any] = ["origin": origin, "timeoutMs": testURL == nil ? 3500 : 400,
            "parseDOM": true, "domPath": testURL?.path ?? "/codex/cloud/settings/analytics"]
        if let expectedIdentity { options["expectedIdentity"] = expectedIdentity }
        evaluating = true
        web.callAsyncJavaScript(script, arguments: ["options": options], in: nil, in: .defaultClient) { [weak self] response in
            guard let self, self.reading, self.generation == epoch else { return }
            self.evaluating = false
            guard self.canCollect(web.url) else { self.finish(["category": "auth_required"]); return }
            switch response {
            case .failure:
                self.finish(["category": "javascript_error"])
            case .success(let value):
                guard var result = value as? [String: Any] else { self.finish(["category": "schema_changed"]); return }
                if result["category"] as? String == "schema_changed", !self.fallbackNavigation,
                   self.testURL == nil, web.url?.path != "/codex/cloud/settings/analytics" {
                    self.fallbackNavigation = true
                    self.load(self.usage)
                    return
                }
                // 页面身份或导航发生变化的结果不能跨越原生提交边界。
                if result["category"] as? String == "success" {
                    let key = (result["identity"] as? [String: Any])?["key"] as? String
                    if key == nil || (self.expectedIdentity != nil && key != self.expectedIdentity) {
                        result["category"] = "account_mismatch"
                        result.removeValue(forKey: "usage")
                    }
                }
                let fields: Set<String> = ["schema", "category", "identity", "usage", "requests", "checked_at", "elapsed_ms", "source_detail"]
                self.finish(result.filter { fields.contains($0.key) })
            }
        }
    }
    func finish(_ result: [String: Any]) {
        generation += 1
        reading = false
        evaluating = false
        let ids = pending
        pending.removeAll()
        let automatic = autoRead
        autoRead = false
        let category = result["category"] as? String ?? "internal_error"
        if category == "success" {
            state = "ready"
            processFailures = 0
            status.stringValue = "额度已同步"
            if loginActive { hideWindow() }
        } else {
            state = category == "auth_required" ? "awaiting_login" : "error"
            let labels = ["auth_required": "请完成登录", "account_mismatch": "网页账号与当前 Token BI 账号不同，请切换至同一账号",
                          "identity_changed": "读取期间账号变化，请重试", "identity_unknown": "暂时无法确认账号",
                          "rate_limited": "请求受限，请稍后再试", "challenge": "请完成网页验证", "timeout": "读取超时，请稍后重试",
                          "network_error": "网络暂不可用，已保留上次额度", "access_denied": "网页拒绝访问，请查看网站提示"]
            status.stringValue = labels[category] ?? "额度暂不可用，请稍后重试"
        }
        for id in ids { reply(id, result) }
        if category == "auth_required", loginActive, !loginRedirected, testURL == nil, canCollect(web?.url) {
            loginRedirected = true
            load("https://chatgpt.com/auth/login")
        }
        if automatic && category == "success" { send(["event": "session_ready"]) }
    }
    func cancelRead() {
        if reading || !pending.isEmpty { finish(["category": "cancelled"]) }
        generation += 1
    }
    func makeContent(_ web: WKWebView) -> NSView {
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 8
        root.edgeInsets = NSEdgeInsets(top: 10, left: 10, bottom: 10, right: 10)
        let bar = NSStackView()
        let retry = NSButton(title: "读取额度", target: self, action: #selector(retryRead))
        retry.bezelStyle = .rounded
        retry.image = NSImage(systemSymbolName: "arrow.clockwise", accessibilityDescription: "读取额度")
        let login = NSButton(title: "登录网页", target: self, action: #selector(openLogin))
        login.bezelStyle = .rounded
        bar.addArrangedSubview(login)
        bar.addArrangedSubview(retry)
        root.addArrangedSubview(bar)
        status.font = .systemFont(ofSize: 12)
        root.addArrangedSubview(status)
        root.addArrangedSubview(web)
        web.translatesAutoresizingMaskIntoConstraints = false
        web.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -20).isActive = true
        web.heightAnchor.constraint(greaterThanOrEqualToConstant: 400).isActive = true
        return root
    }
    func showWindow() {
        if window == nil, let web {
            let created = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
                                   styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            created.title = "Token BI · 账号登录"
            created.minSize = NSSize(width: 720, height: 540)
            created.isReleasedWhenClosed = false
            created.delegate = self
            created.contentView = makeContent(web)
            created.center()
            window = created
        }
        if testURL == nil {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }
    func hideWindow() {
        loginActive = false
        window?.orderOut(nil)
        for popup in popups { popup.orderOut(nil) }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if sender === window { cancelRead(); hideWindow(); send(["event": "login_closed"]); return false }
        return true
    }
    @objc func retryRead() { startRead(id: nil) }
    @objc func openLogin() { cancelRead(); loginRedirected = true; load(testURL?.absoluteString ?? "https://chatgpt.com/auth/login") }
    func installMenu() {
        let menu = NSMenu()
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard allowed(action.request.url, source: action.sourceFrame.request.url, main: action.targetFrame?.isMainFrame ?? true) else {
            if webView === web, action.targetFrame?.isMainFrame == true, reading { finish(["category": "navigation_blocked"]) }
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === web else { return }
        if reading {
            if canCollect(webView.url) { collect(generation) }
            else { finish(["category": "auth_required"]) }
        } else if loginActive, canCollect(webView.url), loginAttempts < 4 {
            loginAttempts += 1
            let epoch = generation
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
                guard let self, self.loginActive, self.generation == epoch else { return }
                self.startRead(id: nil)
            }
        }
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        // 采集中切换页面会更换 JS 上下文，旧页面结果不能提交。
        if webView === web, evaluating { finish(["category": "cancelled"]) }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard webView === web, (error as NSError).code != NSURLErrorCancelled else { return }
        if reading { finish(["category": "network_error"]) }
        status.stringValue = "网页加载失败，请检查网络"
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        self.webView(webView, didFailProvisionalNavigation: navigation, withError: error)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        guard webView === web else { return }
        processFailures += 1
        lastProcessFailure = Date()
        finish(["category": "web_process_terminated"])
        web = nil
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard loginActive, allowed(action.request.url), testURL == nil else { return nil }
        let child = WKWebView(frame: .zero, configuration: configuration)
        child.navigationDelegate = self
        child.uiDelegate = self
        let popup = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 700),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        popup.title = "Token BI · 账号登录"
        popup.isReleasedWhenClosed = false
        popup.contentView = child
        popup.delegate = self
        popups.append(popup)
        popup.center()
        popup.makeKeyAndOrderFront(nil)
        return child
    }
    func webViewDidClose(_ webView: WKWebView) {
        popups.first(where: { $0.contentView === webView })?.close()
        popups.removeAll(where: { $0.contentView === webView })
    }
    func dialog(_ webView: WKWebView, frame: WKFrameInfo, message: String,
                kind: String, defaultText: String? = nil, completion: @escaping (Bool, String?) -> Void) {
        guard loginActive, allowed(frame.request.url), let parent = webView.window, testURL == nil else {
            completion(false, nil); return
        }
        let alert = NSAlert()
        alert.messageText = "网页提示 · \(frame.request.url?.host ?? "")"
        alert.informativeText = String(message.prefix(8000))
        alert.addButton(withTitle: "确定")
        if kind != "alert" { alert.addButton(withTitle: "取消") }
        let input = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        if kind == "prompt" { input.stringValue = defaultText ?? ""; alert.accessoryView = input }
        alert.beginSheetModal(for: parent) { response in
            completion(response == .alertFirstButtonReturn, kind == "prompt" ? input.stringValue : nil)
        }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        dialog(webView, frame: frame, message: message, kind: "alert") { _, _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        dialog(webView, frame: frame, message: message, kind: "confirm") { accepted, _ in completionHandler(accepted) }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        dialog(webView, frame: frame, message: prompt, kind: "prompt", defaultText: defaultText) { accepted, text in
            completionHandler(accepted ? text : nil)
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main enum WebSessionMain {
    static func main() {
        guard CommandLine.arguments.contains("--stdio") else { return }
        let app = NSApplication.shared
        app.setActivationPolicy(CommandLine.arguments.contains("--fixture") ? .prohibited : .accessory)
        let session = WebSession()
        app.delegate = session
        app.run()
    }
}
