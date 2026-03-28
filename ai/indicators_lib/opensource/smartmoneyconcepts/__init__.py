import os
from smartmoneyconcepts.smc import smc

if os.getenv('SMC_CREDIT', '1') == '1':
    print("\033[1;33mThank you for using SmartMoneyConcepts! ⭐ Please show your support by giving a star on the GitHub repository: \033[4;34mhttps://github.com/joshyattridge/smart-money-concepts\033[0m")