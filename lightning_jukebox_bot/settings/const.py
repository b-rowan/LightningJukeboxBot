import random
import string
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
QR_CODE_DIR = BASE_DIR.joinpath("tmp")

TG_SECRET = "".join(random.sample(string.ascii_letters, 12))
