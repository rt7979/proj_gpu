#  ********************************************
#  *
#  * 刪除螢幕的魔法
#  *
#  ********************************************

import os
import subprocess

def clear():
    _ = subprocess.run('cls' if os.name == 'nt' else 'clear', shell=True)    # 清除螢幕的魔法
    print("--- 呼叫螢幕清除魔法 ---\n\n")
    return