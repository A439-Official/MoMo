import shutil
import os
import time
import sys
import CFVI.deepseek
import CFVI.os
import CFVI.cli
import subprocess
import json
import datetime
import colorama
import concurrent.futures
import math
import random
import requests
import urllib3
import packaging.version

# 常量定义
NAME = "MoMo"
CREATOR = "A439"
VERSION = "0.4.1"
DECAY_CONSTANT = math.log(2) / (60 * 60 * 24 * 7)  # 记忆衰减常数

# 路径和初始化
app_data_dir = f"{os.environ.get('APPDATA')}\\{CREATOR}\\{NAME}"
mem_path = os.path.join(app_data_dir, "memory.json")
settings_path = os.path.join(app_data_dir, "settings.json")
characters_path = os.path.join(app_data_dir, "characters.json")

# 全局变量
memory = []
settings = {}
characters = {}
ai = None
screen = CFVI.cli.CLIRender()
_executor = concurrent.futures.ThreadPoolExecutor()


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_console_width():
    return shutil.get_terminal_size().columns


def clear_console():
    print("\033[2J\033[H", end="")


def clear_line():
    sys.stdout.write("\033[F\033[K\r")
    sys.stdout.flush()


# 命令执行函数(PowerShell)
def cmd_async(command, directory, timeout=10, callback=None):
    if not directory:
        directory = os.getcwd()

    def _run_command():
        try:
            if not os.path.exists(directory):
                return f'错误: 目录 "{directory}" 不存在'
            ps_command = f"powershell -Command \"& {{Set-Location '{directory}'; {command}}}\""
            result = subprocess.run(ps_command, shell=True, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)
            output = result.stdout
            if result.stderr:
                output += f"\n错误信息:\n{result.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return f"命令执行超时({timeout}秒)"
        except Exception as e:
            return f"执行命令时发生异常: {str(e)}"

    future = _executor.submit(_run_command)
    if callback:

        def callback_wrapper(f):
            try:
                callback(f.result())
            except Exception as e:
                callback(f"获取结果时发生错误: {str(e)}")

        future.add_done_callback(callback_wrapper)
    return future


def cmd(command, directory, timeout=10):
    future = cmd_async(command, directory, timeout)
    try:
        return future.result(timeout=timeout + 5)
    except TimeoutError:
        return f"命令执行超时({timeout}秒), 但程序可能在后台继续运行"


# 磁盘和文件操作
def get_disk_info():
    if os.name == "nt":
        return [f"{d}:\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
    else:
        mounts = []
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if parts[0].startswith("/dev/"):
                    mounts.append(parts[1])
        return mounts


def load_json_file(file_path, default_value):
    if not CFVI.os.check_file_exists(file_path):
        return default_value
    try:
        with CFVI.os.FileUnlocker(file_path):
            with open(file_path, "r", encoding="utf8") as f:
                content = f.read().strip()
                return json.loads(content) if content else default_value
    except (json.JSONDecodeError, FileNotFoundError):
        return default_value


def save_json_file(file_path, data):
    with CFVI.os.FileUnlocker(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# 记忆系统
def calculate_current_importance(memory_item):
    if "importance" not in memory_item:
        memory_item["importance"] = 1.0
    memory_time = datetime.datetime.fromisoformat(memory_item["time"])
    elapsed_seconds = (datetime.datetime.now() - memory_time).total_seconds()
    current_importance = memory_item["importance"] * math.exp(-DECAY_CONSTANT * elapsed_seconds)
    return max(0.01, current_importance)


def add_to_memory(memory_list, message, importance_boost=0):
    for item in memory_list:
        item["current_importance"] = calculate_current_importance(item)
    new_memory = {
        "time": datetime.datetime.now().isoformat(),
        "message": message,
        "importance": 1.0 + importance_boost,
        "current_importance": 1.0 + importance_boost,
    }
    memory_list.append(new_memory)
    memory_list.sort(key=lambda x: x.get("current_importance", 0), reverse=True)
    return memory_list[:1000] if len(memory_list) > 1000 else memory_list


def boost_memory_importance(memory_list, indices, boost_amount=0.5):
    for idx in indices:
        if 0 <= idx < len(memory_list):
            memory_list[idx]["importance"] += boost_amount
            memory_list[idx]["current_importance"] = calculate_current_importance(memory_list[idx])
    return memory_list


def get_top_memories(memory_list, count=32):
    for item in memory_list:
        item["current_importance"] = calculate_current_importance(item)
    sorted_memories = sorted(memory_list, key=lambda x: x.get("current_importance", 0), reverse=True)
    return sorted_memories[:count]


def reload_ai():
    """重新加载AI配置，用于切换API或角色时调用"""
    global ai, memory, settings
    ai = CFVI.deepseek.DeepSeek(settings.get("base_url", "https://api.siliconflow.cn/v1/"), settings.get("api_key", "sk-enbhvbmgdndpkvznavkwqbdnafwmvsugjczzuwmeradypbdu"), settings.get("model", "Qwen/Qwen3-8B"))
    ai.add_message(
        f"""
{characters.get(settings.get("character", "momo"), characters["momo"])}
{open(resource_path("resources/rules.txt"), "r", encoding="utf8").read()}
用户的电脑信息: 
{env}
你的记忆: 
{"\n".join(f"{m['time']}: {m['message']}" for m in get_top_memories(memory, 32))}
""",
        "system",
    )


# 命令处理函数
def command_about(*args):
    print(
        f"""
{NAME}
版本: {VERSION}
作者: {CREATOR}

是猫娘沫沫喵~
可以来找我聊天解闷的喵(ฅ´ω`ฅ)
"""
    )


def command_settings(*args):
    global settings
    if not args:
        print("这些是当前的设置喵:")
        print("\n".join([f"{key}: {value}" for key, value in settings.items()]))
    elif len(args) == 1:
        if args[0] == "reset":
            settings = {}
            reload_ai()
            print("设置已经全部重置为默认值了喵!")
        elif args[0] in settings:
            print(f"{args[0]}: {settings[args[0]]}")
        else:
            print(f"找不到{args[0]}这个设置项喵...")
    elif len(args) == 2:
        if args[0] == "del":
            if args[1] in settings:
                del settings[args[1]]
                save_json_file(settings_path, settings)
                reload_ai()
                print(f"已经删掉了设置{args[1]}喵!")
            else:
                print(f"找不到{args[0]}这个设置项喵...")
        else:
            print(f"参数不正确喵! 要不要看看帮助喵?")
    elif len(args) == 3:
        if args[0] == "set":
            if args[1] in ["base_url", "api_key", "model"]:
                settings[args[1]] = args[2]
                save_json_file(settings_path, settings)
                reload_ai()
                print(f"已经把{args[1]}改成{args[2]}了喵!")
            else:
                print(f"找不到{args[1]}这个设置项喵...")
        else:
            print(f"参数不正确喵! 要不要看看帮助喵?")
    else:
        print(f"参数不正确喵! 要不要看看帮助喵?")


def command_character(*args):
    global characters, settings, ai
    if not args:
        print("有这些角色喵:")
        for i, (char_name, char_desc) in enumerate(characters.items()):
            print(f"  {i+1}. {char_name}[{'内置' if char_name in inlay_characters else '自定义'}]")
        print(f"现在是在和{'沫沫' if settings.get('character', 'momo') == 'momo' else settings.get('character', 'momo')}聊天喵{'(ฅ>ω<*ฅ)' if settings.get('character', 'momo') == 'momo' else ''}")
    elif len(args) == 1:
        if args[0] in characters:
            settings["character"] = args[0]
            save_json_file(settings_path, settings)
            reload_ai()
            print(f"已切换到{'沫沫' if args[0] == 'momo' else args[0]}了喵!")
        else:
            print(f"找不到{args[0]}喵...")
    elif len(args) >= 2:
        if args[0] == "add":
            char_name = args[1]
            char_desc = " ".join(args[2:]) if len(args) > 2 else input("请输入角色描述喵:")
            char_desc = char_desc.replace("\\n", "\n")
            if not char_desc.strip():
                print("角色描述不能为空喵...")
                return
            if char_name in inlay_characters:
                print(f"不能覆盖内置角色喵...")
                return
            characters[char_name] = char_desc
            save_json_file(characters_path, {k: v for k, v in characters.items() if k not in inlay_characters})
            print(f"已经添加了角色{char_name}喵!")
        elif args[0] == "del":
            char_name = args[1]
            if char_name in inlay_characters:
                print(f"不能删除内置角色喵...")
                return
            if char_name in characters:
                del characters[char_name]
                save_json_file(characters_path, {k: v for k, v in characters.items() if k not in inlay_characters})
                print(f"已经删除了{char_name}喵! 拜拜ヾ(•ω•`)o")
                if settings.get("character") == char_name:
                    settings["character"] = "momo"
                    save_json_file(settings_path, settings)
                    reload_ai()
                    print("已经自动切换回沫沫了喵~")
            else:
                print(f"找不到{args[0]}喵...")
        elif args[0] == "edit":
            char_name = args[1]
            if char_name in inlay_characters:
                print(f"不能编辑内置角色喵...")
                return
            if char_name in characters:
                new_desc = " ".join(args[2:]) if len(args) > 2 else input(f"当前描述: {characters[char_name]}\n请输入新的描述喵: ")
                new_desc = new_desc.replace("\\n", "\n")
                if not new_desc.strip():
                    print("角色描述不能为空喵...")
                    return
                characters[char_name] = new_desc
                save_json_file(characters_path, {k: v for k, v in characters.items() if k not in inlay_characters})
                if settings.get("character") == char_name:
                    reload_ai()
                print(f"已经更新了{char_name}的描述喵!")
            else:
                print(f"找不到{args[0]}喵...")
        else:
            print("参数不正确喵! 要不要看看帮助喵?")
    else:
        print("参数不正确喵! 要不要看看帮助喵?")


def command_quit(*args):
    global memory, settings
    screen.add_rect(0, 0, screen.get_size()[0], 3, (255, 128, 255), True)
    screen.add_text(1, 1, "再见喵~", (255, 255, 255))
    screen.render(True)
    print()

    memory.sort(key=lambda x: x.get("current_importance", 0), reverse=True)
    save_json_file(mem_path, memory)
    save_json_file(settings_path, settings)
    save_json_file(characters_path, {k: v for k, v in characters.items() if k not in inlay_characters})

    CFVI.os.lock_file(settings_path)
    CFVI.os.lock_file(os.path.dirname(mem_path))
    print(colorama.Fore.RESET, end="")
    sys.exit(0)


# 初始化
colorama.init()
creator_said = open(resource_path("resources/creatorsaid.txt"), "r", encoding="utf8").read().split("\n")
CFVI.os.unlock_file(app_data_dir)

# 欢迎界面
welcome = open(resource_path("resources/welcome.txt"), "r", encoding="utf8").read()
welcome_text = CFVI.cli.replace_ex(welcome, "$\n")
welcome_shadow = CFVI.cli.replace_ex(welcome, "/|\\_\n")

os.system("cls")
screen.add_rect(0, 0, screen.get_size()[0], screen.get_size()[1], (255, 128, 255), True)
screen.add_text(1, 1, welcome_text, (128, 255, 255), screen.get_size()[0] - 2, screen.get_size()[1] - 2)
screen.add_text(1, 1, welcome_shadow, (255, 128, 255), screen.get_size()[0] - 2, screen.get_size()[1] - 2)
screen.render()
time.sleep(0.439)

st = time.time()
while time.time() - st < 1:
    clear_console()
    progress = round((1 - (time.time() - st) ** 5) * screen.get_size()[1])
    screen.add_rect(0, 0, screen.get_size()[0], progress, (255, 128, 255), True)
    screen.add_text(1, 1, welcome_text, (128, 255, 255), screen.get_size()[0] - 2, progress - 2)
    screen.add_text(1, 1, welcome_shadow, (255, 128, 255), screen.get_size()[0] - 2, progress - 2)
    screen.render()

os.system("cls")
screen.add_rect(0, 0, screen.get_size()[0], 3, (255, 128, 255), True)
screen.add_text(1, 1, f"{NAME}", (255, 255, 255), screen.get_size()[0] - 2, 2)
screen.add_text(1, 1, f"{len(NAME) * ' '} v{VERSION}", (128, 128, 128), screen.get_size()[0] - 2, 2)
screen.render(True)
print()

# 环境信息
env = f"""
系统名: {os.name}
用户: {os.environ.get('USER') or os.environ.get('USERNAME')}
磁盘: {get_disk_info()}
"""

# 加载数据
memory = load_json_file(mem_path, [])
settings = load_json_file(settings_path, {})
for mem in memory:
    if "importance" not in mem:
        mem["importance"] = 1.0

# 初始化角色
inlay_characters = json.load(open(resource_path("resources/characters.json"), "r", encoding="utf8"))
characters = inlay_characters.copy()
if os.path.exists(characters_path):
    characters |= json.load(open(characters_path, "r", encoding="utf8"))

if settings.get("character", "momo") not in characters:
    print(f"找不到{settings['character']}喵, 让沫沫来陪主人喵!")
    settings["character"] = "momo"

reload_ai()


# 命令管理器
command_manager = CFVI.cli.CommandManager()
command_manager.add_command("about", command_about)
command_manager.set_desc("about", "关于喵")
command_manager.add_command("?", command_manager.command_help)
command_manager.set_desc("?", "帮助喵")
command_manager.add_command("quit", command_quit)
command_manager.set_desc("quit", "退出(真的要离开沫沫吗QAQ)")
command_manager.add_command("settings", command_settings)
command_manager.set_desc("settings", "管理设置喵")
command_manager.set_help(
    "settings",
    """用法:
/settings - 查看所有设置
/settings <名称> - 查看指定设置
/settings set <名称> <值> - 更改指定设置
/settings del <名称> - 删除指定设置
/settings reset - 重置所有设置

可设置的项:
base_url - API地址
api_key - API密钥
model - 模型""",
)
command_manager.add_command("character", command_character)
command_manager.set_desc("character", "管理角色喵")
command_manager.set_help(
    "character",
    """用法:
/character - 显示所有角色
/character <角色名> - 切换到指定角色
/character add <角色名> [描述] - 添加新角色
/character del <角色名> - 删除角色
/character edit <角色名> [新描述] - 编辑角色描述""",
)
command_manager.add_command("creatorsaid", lambda *args: print(random.choice(creator_said)))
command_manager.set_desc("creatorsaid", "作者说(什么乱七八糟的喵")

# 检查更新
try:
    print(CFVI.cli.colorize_text("正在获取更新喵...", (128, 128, 128)), end="", flush=True)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(f"https://api.github.com/repos/A439-Official/{NAME}/releases/latest", verify=False, timeout=10).json()
    print("\r", end="")
    if isinstance(response, dict):
        response = [response]
    if response and response[0]["tag_name"] != VERSION and packaging.version.parse(response[0]["tag_name"]) > packaging.version.parse(VERSION):
        print(CFVI.cli.colorize_text(f"发现新版本{response[0]['tag_name']}喵: {response[0]['assets'][0]['browser_download_url']}", (255, 128, 0)))
        print(CFVI.cli.colorize_text(response[0]["body"], (128, 128, 128)))
except Exception as e:
    print("\r", end="")
    print(CFVI.cli.colorize_text(f"获取更新失败喵! {str(e)}", (255, 0, 0)))

print(CFVI.cli.colorize_text(f"使用/help查看可用命令喵", (128, 128, 128)))
if not settings.get("base_url"):
    print(CFVI.cli.colorize_text("""警告: API还没有设置, 默认地址很可能无法正常工作喵!""", (255, 128, 0)))

# 主循环
question = ""
while True:
    try:
        question = input(CFVI.cli.colorize_text(">", (192, 192, 192)) + "\033[38;2;128;255;255m")
    except:
        question = "/quit"
        print("\033[38;2;128;255;255m" + question)
    if not question:
        continue
    print(colorama.Fore.RESET, end="")

    if command_manager.is_command(question):
        command_manager.run(question)
        continue

    result, token = None, None
    while True:
        try:
            if result is None:
                result, token = ai.chat(json.dumps({"time": datetime.datetime.now().isoformat(), "message": question}))

            if result.startswith("```json"):
                result = result[7:-3]
            answer = json.loads(result.strip())

            height = screen.add_text(1, 1, f"{answer['message']}({token['total_tokens']})", (255, 255, 255), screen.get_size()[0] - 2)
            screen.add_rect(0, 0, screen.get_size()[0], height + 2, (255, 128, 255), True)
            screen.render(True)
            print()

            if "iptmem" in answer and isinstance(answer["iptmem"], list):
                memory = boost_memory_importance(memory, answer["iptmem"], boost_amount=0.5)
            if answer.get("remember", ""):
                memory = add_to_memory(memory, answer["remember"])
                save_json_file(mem_path, memory)
            if not answer.get("cmd", ""):
                break

            print(CFVI.cli.colorize_text(f"{answer.get('cmd_dir', '')}>{answer['cmd']}", (64, 64, 64)))
            result = cmd(answer["cmd"].replace("§file§", answer.get("file", "")), answer.get("file", ""))
            result, token = ai.chat(result)

        except Exception as e:
            print(CFVI.cli.colorize_text(f"出错了喵TwT: {str(e)}", (255, 0, 0)))
            print(CFVI.cli.colorize_text(f"对话详情: {str(result)}", (64, 64, 64)))
            print(CFVI.cli.colorize_text(f"复制或截图此对话并联系作者以修复喵~", (64, 64, 64)))
            break
