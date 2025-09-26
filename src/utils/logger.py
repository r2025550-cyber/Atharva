from loguru import logger
import sys, os

level = os.getenv("LOG_LEVEL", "INFO").upper()
logger.remove()
logger.add(sys.stdout, level=level, enqueue=True, backtrace=False, diagnose=False)
