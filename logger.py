import logging
import json
import sys

class JSONFormatter(logging.Formatter):
    """Custom formatter to output log messages as JSON."""
    
    def format(self, record):
        log_record = {
            'timestamp': self.formatTime(record, self.default_time_format),
            'level': record.levelname,
            'module': record.module,
            'message': record.getMessage(),
        }
        return json.dumps(log_record)

def setup_logger(name):
    """Set up a logger with a JSON formatter."""
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

# Example usage
logger = setup_logger('my_logger')
logger.info('Logger is set up.')
