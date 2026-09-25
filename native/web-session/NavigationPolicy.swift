import Foundation

enum NavigationPolicy {
    static let hosts: Set<String> = [
        "chatgpt.com", "auth.openai.com", "auth0.openai.com", "auth.chatgpt.com",
        "accounts.google.com", "appleid.apple.com", "login.microsoftonline.com",
        "login.live.com", "challenges.cloudflare.com"
    ]
    static func secure(_ url: URL) -> Bool {
        url.scheme == "https" && (url.port == nil || url.port == 443) && url.user == nil && url.password == nil
    }
    static func allowed(_ url: URL?, source: URL? = nil, main: Bool = true) -> Bool {
        guard let url else { return false }
        if url.absoluteString == "about:blank" { return true }
        guard secure(url) else { return false }
        if hosts.contains(url.host ?? "") { return true }
        guard !main, url.host == "sentinel.openai.com", let source, secure(source) else { return false }
        return ["chatgpt.com", "auth.openai.com", "auth0.openai.com", "auth.chatgpt.com", "sentinel.openai.com"].contains(source.host ?? "")
    }
}
