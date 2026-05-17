

class NovelWriterError(Exception):
    pass


class DeepSeekAPIError(NovelWriterError):
    pass


class ContractError(NovelWriterError):
    pass
