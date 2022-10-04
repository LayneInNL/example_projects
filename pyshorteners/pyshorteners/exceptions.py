class ShorteningErrorException(Exception):
    def __init__(self, message=None):
        super(Exception, self).__init__(f'There was an error on trying to short the url: '
                         f'{message}')


class ExpandingErrorException(Exception):
    def __init__(self, message=None):
        super(Exception, self).__init__(f'There was an error on trying to expand the url: '
                         f'{message}')


class BadAPIResponseException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(f'Error on API Response: {message}')


class BadURLException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(f'URL is not valid: {message}')
