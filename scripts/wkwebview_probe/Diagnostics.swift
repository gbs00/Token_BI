import Foundation

// 页面脚本也视为不可信输入，写盘前仅保留固定枚举和有界数值。
final class ProbeDiagnostics {
    static let events: Set<String> = [
        "page_ready", "submit_click", "form_submit", "invalid_input",
        "fetch_start", "fetch_end", "fetch_error", "xhr_start", "xhr_end", "xhr_error",
        "script_error", "promise_error", "resource_error", "navigation_allowed", "navigation_blocked",
        "navigation_response", "navigation_failed", "popup_opened", "popup_blocked",
        "dialog_alert", "dialog_confirm", "dialog_prompt", "web_process_terminated"
    ]
    private(set) var rows: [[String: Any]] = []
    var changed: (() -> Void)?

    func record(_ event: String, fields: [String: Any] = [:]) {
        guard Self.events.contains(event) else { return }
        var row: [String: Any] = ["event": event, "time": ISO8601DateFormatter().string(from: Date())]
        let enums: [String: Set<String>] = [
            "target": ["chatgpt", "auth", "challenge", "identity_provider", "local", "other", "none"],
            "route": ["password", "session", "challenge", "usage", "auth_api", "login", "asset", "other"],
            "error_kind": ["TypeError", "ReferenceError", "SyntaxError", "RangeError", "AbortError", "other"]
        ]
        for (key, options) in enums {
            if let value = fields[key] as? String, options.contains(value) { row[key] = value }
        }
        if let site = fields["site"] as? String,
           ["openai.com", "chatgpt.com", "oaistatic.com", "cloudflare.com", "auth0.com"].contains(where: { site == $0 || site.hasSuffix("." + $0) }),
           site.count <= 120, site.range(of: "^[a-z0-9.-]+$", options: .regularExpression) != nil {
            row["site"] = site
        }
        if let scheme = fields["scheme"] as? String, ["https", "http", "about", "blob", "data"].contains(scheme) {
            row["scheme"] = scheme
        }
        if let value = fields["status"] as? Int, (0...599).contains(value) { row["status"] = value }
        if let value = fields["error_code"] as? Int, (-100000...100000).contains(value) { row["error_code"] = value }
        for key in ["main_frame", "disabled"] {
            if let value = fields[key] as? Bool { row[key] = value }
        }
        rows.append(row)
        if rows.count > 200 { rows.removeFirst(rows.count - 200) }
        changed?()
    }

    static func endpoint(_ url: URL?) -> [String: Any] {
        guard let url else { return ["target": "none", "route": "other"] }
        let hosts = ["chatgpt.com": "chatgpt", "auth.openai.com": "auth", "auth0.openai.com": "auth",
                     "auth.chatgpt.com": "auth", "challenges.cloudflare.com": "challenge",
                     "accounts.google.com": "identity_provider", "appleid.apple.com": "identity_provider",
                     "login.microsoftonline.com": "identity_provider", "login.live.com": "identity_provider",
                     "127.0.0.1": "local"]
        let path = url.path
        let route = path.contains("password") ? "password" : path.contains("/api/auth/session") ? "session"
            : path.contains("challenge") || path.contains("sentinel") ? "challenge" : path.contains("wham") ? "usage"
            : path.contains("/api/accounts") ? "auth_api" : path.contains("log-in") || path.contains("login") || path.contains("authorize") ? "login"
            : path.hasSuffix(".js") || path.hasSuffix(".css") ? "asset" : "other"
        return ["target": hosts[url.host ?? ""] ?? "other", "route": route,
                "site": url.host ?? "", "scheme": url.scheme ?? ""]
    }
}
