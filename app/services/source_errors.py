"""各数据源共用的错误语义，与网页引擎实现解耦。"""


class ScraperUnavailableError(RuntimeError):
    pass


class SessionExpiredError(ScraperUnavailableError):
    pass


class AnalyticsPageChangedError(ScraperUnavailableError):
    pass


class LiveSessionRequiredError(ScraperUnavailableError):
    pass


class AccountMismatchError(AnalyticsPageChangedError):
    pass
