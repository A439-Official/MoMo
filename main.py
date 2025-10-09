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
import subprocess
import concurrent.futures
import math
import random


NAME = "MoMo"
CREATOR = "A439"
VERSION = "0.3.0"
VERSION_DESC = "增加了完善（？）的命令系统"


# 记忆衰减常数 - 每天重要性衰减50%
DECAY_CONSTANT = math.log(2) / (60 * 60 * 24 * 7)


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_console_width():
    """控制台宽度"""
    return shutil.get_terminal_size().columns


def clear_console():
    """清空控制台"""
    print("\033[2J\033[H", end="")


def clear_line():
    sys.stdout.write("\033[F")
    sys.stdout.write("\033[K")
    sys.stdout.write("\r")
    sys.stdout.flush()


_executor = concurrent.futures.ThreadPoolExecutor()


def cmd_async(command, directory, timeout=10, callback=None):
    """
    异步执行CMD命令

    Args:
        command (str): 要执行的命令
        directory (str): 执行命令的目录路径
        timeout (int): 命令执行超时时间（秒）
        callback (callable): 完成后回调函数，接收结果作为参数

    Returns:
        concurrent.futures.Future: 未来对象，可用于获取结果
    """
    if directory == "":
        directory = os.getcwd()

    def _run_command():
        try:
            if not os.path.exists(directory):
                return f'错误：目录 "{directory}" 不存在'

            result = subprocess.run(
                command,
                shell=True,
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore",
                timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n错误信息:\n{result.stderr}"
            return output

        except subprocess.TimeoutExpired:
            return f"命令执行超时（{timeout}秒）"
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


# 同步版本的包装器（保持原有接口）
def cmd(command, directory, timeout=10):
    """执行命令（内部使用异步实现）"""
    future = cmd_async(command, directory, timeout)
    try:
        return future.result(timeout=timeout + 5)  # 额外给5秒缓冲
    except TimeoutError:
        return f"命令执行超时（{timeout}秒），但程序可能在后台继续运行"


def get_disk_info():
    if os.name == "nt":  # Windows系统
        # 获取所有可能的驱动器字母
        drives = [f"{d}:\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
        return drives
    else:  # Linux/Mac系统
        # 获取挂载点
        mounts = []
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if parts[0].startswith("/dev/"):
                    mounts.append(parts[1])
        return mounts


def load_json_file(file_path, default_value):
    """加载JSON文件，如果文件不存在或格式错误，返回默认值"""
    if not CFVI.os.check_file_exists(file_path):
        return default_value

    try:
        with CFVI.os.FileUnlocker(file_path):
            with open(file_path, "r", encoding="utf8") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                else:
                    return default_value
    except (json.JSONDecodeError, FileNotFoundError):
        return default_value


def save_json_file(file_path, data):
    """保存数据到JSON文件"""
    with CFVI.os.FileUnlocker(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def calculate_current_importance(memory_item):
    """计算记忆项的当前重要性（考虑时间衰减）"""
    if "importance" not in memory_item:
        memory_item["importance"] = 1.0  # 默认重要性

    # 计算经过的时间（秒）
    memory_time = datetime.datetime.fromisoformat(memory_item["time"])
    elapsed_seconds = (datetime.datetime.now() - memory_time).total_seconds()

    # 应用指数衰减
    current_importance = memory_item["importance"] * math.exp(-DECAY_CONSTANT * elapsed_seconds)
    return max(0.01, current_importance)  # 确保重要性不低于0.01


def add_to_memory(memory_list, message, importance_boost=0):
    """添加新记忆到记忆列表，可选增加重要性"""
    # 首先衰减所有现有记忆的重要性
    for item in memory_list:
        item["current_importance"] = calculate_current_importance(item)

    # 添加新记忆
    new_memory = {
        "time": datetime.datetime.now().isoformat(),
        "message": message,
        "importance": 1.0 +
        # 基础重要性1.0 + 额外提升  # 当前重要性
        importance_boost,
        "current_importance": 1.0 + importance_boost,
    }
    memory_list.append(new_memory)

    # 按当前重要性排序，保留最重要的1000条记忆
    memory_list.sort(key=lambda x: x.get("current_importance", 0), reverse=True)
    if len(memory_list) > 1000:
        memory_list = memory_list[:1000]

    return memory_list


def boost_memory_importance(memory_list, indices, boost_amount=0.5):
    """增加指定索引记忆的重要性"""
    for idx in indices:
        if 0 <= idx < len(memory_list):
            memory_list[idx]["importance"] += boost_amount
            memory_list[idx]["current_importance"] = calculate_current_importance(memory_list[idx])
    return memory_list


def get_top_memories(memory_list, count=32):
    """获取最重要的记忆"""
    # 首先更新所有记忆的当前重要性
    for item in memory_list:
        item["current_importance"] = calculate_current_importance(item)

    # 按重要性排序并返回前count条
    sorted_memories = sorted(memory_list, key=lambda x: x.get("current_importance", 0), reverse=True)
    return sorted_memories[:count]


def command_about(*args):
    """显示关于信息"""
    print(
        f"""
{NAME}
版本：{VERSION} - {VERSION_DESC}
作者：{CREATOR}

是猫娘沫沫喵~
可以来找我聊天解闷的喵！
"""
    )


def command_settings(*args):
    global settings
    """管理设置"""
    if len(args) == 0:
        print("\n".join([f"{key}: {value}" for key, value in settings.items()]))
    elif len(args) == 1:
        if args[0] == "reset":
            settings = {}
        elif args[0] in settings:
            print(f"{args[0]}: {settings[args[0]]}")
        else:
            print(f"找不到设置 {args[0]}")
    elif len(args) == 2:
        if args[0] == "del":
            if args[1] in settings:
                del settings[args[1]]
                save_json_file(settings_path, settings)
                print(f"设置 {args[1]} 已删除")
            else:
                print(f"找不到设置 {args[0]}")
        else:
            print(f"错误的参数")
    elif len(args) == 3:
        if args[0] == "set":
            if args[1] in ["base_url", "api_key", "model"]:
                settings[args[1]] = args[2]
                save_json_file(settings_path, settings)
                print(f"设置 {args[1]} 已设置为 {args[2]}")
            else:
                print(f"不存在的设置 {args[1]}")
        else:
            print(f"错误的参数")
    else:
        print(f"错误的参数")


def command_quit(*args):
    """退出程序"""
    global memory, settings
    screen.add_rect(0, 0, screen.get_size()[0], 3, (255, 128, 255), True)
    screen.add_text(1, 1, "再见喵~", (255, 255, 255))
    screen.render(True)
    print()

    memory.sort(key=lambda x: x.get("current_importance", 0), reverse=True)

    save_json_file(mem_path, memory)
    save_json_file(settings_path, settings)

    CFVI.os.lock_file(settings_path)
    CFVI.os.lock_file(os.path.dirname(mem_path))
    print(colorama.Fore.RESET, end="")
    sys.exit(0)


creator_said = open(resource_path("resources/creatorsaid.txt"), "r", encoding="utf8").read().split("\n")
screen = CFVI.cli.CLIRender()
colorama.init()
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
    # os.system("cls")
    screen.add_rect(0, 0, screen.get_size()[0], round((1 - (time.time() - st) ** 5) * screen.get_size()[1]), (255, 128, 255), True)
    screen.add_text(1, 1, welcome_text, (128, 255, 255), screen.get_size()[0] - 2, round((1 - (time.time() - st) ** 5) * screen.get_size()[1]) - 2)
    screen.add_text(1, 1, welcome_shadow, (255, 128, 255), screen.get_size()[0] - 2, round((1 - (time.time() - st) ** 5) * screen.get_size()[1]) - 2)
    screen.render()
os.system("cls")
screen.add_rect(0, 0, screen.get_size()[0], 3, (255, 128, 255), True)
screen.add_text(1, 1, f"{NAME}", (255, 255, 255), screen.get_size()[0] - 2, 2)
screen.add_text(1, 1, f"{len(NAME) * " "} v{VERSION}", (128, 128, 128), screen.get_size()[0] - 2, 2)
screen.add_text(0, 3, "使用/help查看可用命令", (128, 128, 128))
screen.render(True)
print()

env = f"""
系统名：{os.name}
用户：{os.environ.get("USER") or os.environ.get("USERNAME")}
磁盘：{get_disk_info()}
"""

# 初始化记忆和设置
app_data_dir = f"{os.environ.get("APPDATA")}\\{CREATOR}\\{NAME}"
mem_path = os.path.join(app_data_dir, "memory.json")
settings_path = os.path.join(app_data_dir, "settings.json")

# 加载记忆和设置
memory = load_json_file(mem_path, [])
settings = load_json_file(settings_path, {})

# 更新旧格式的记忆（添加重要性字段）
for mem in memory:
    if "importance" not in mem:
        mem["importance"] = 1.0  # 默认重要性

ai = CFVI.deepseek.DeepSeek(settings.get("base_url", "https://api.siliconflow.cn/v1/"), settings.get("api_key", "sk-enbhvbmgdndpkvznavkwqbdnafwmvsugjczzuwmeradypbdu"), settings.get("model", "Qwen/Qwen3-8B"))
character = open(resource_path("resources/MoMo.txt"), "r", encoding="utf8").read()

ai.add_message(
    f"""
{character}
{open(resource_path("resources/rules.txt"), "r", encoding="utf8").read()}
用户的电脑信息：
{env}
你的记忆：
{"\n".join(f"{m['time']}: {m['message']}" for m in get_top_memories(memory, 32))}
""",
    "system",
)

command_manager = CFVI.cli.CommandManager()
command_manager.add_command("about", command_about)
command_manager.set_desc("about", "关于")
command_manager.add_command("?", command_manager.command_help)
command_manager.set_desc("?", "是/help")
command_manager.add_command("quit", command_quit)
command_manager.set_desc("quit", "退出（真的要离开沫沫吗qwq）")
command_manager.add_command("settings", command_settings)
command_manager.set_desc("settings", "管理设置")
command_manager.set_help(
    "settings",
    """用法:
/settings - 查看所有设置
/settings <key> - 查看指定设置
/settings set <key> <value> - 更改指定设置
/settings del <key> - 删除指定设置
/settings reset - 重置所有设置

可用设置：
base_url - API地址
api_key - API密钥
model - 模型""",
)
command_manager.add_command("creatorsaid", lambda *args: print(random.choice(creator_said)))


if not settings.get("base_url"):
    print(CFVI.cli.colorize_text("""警告：未设置API，默认地址很可能无法正常工作。""", (255, 128, 0)))

question = ""
while True:
    try:
        question: str = input(CFVI.cli.colorize_text(">", (192, 192, 192)) + "\033[38;2;128;255;255m")
    except:
        question = "/quit"
        print("\033[38;2;128;255;255m" + question)
    if question == "":
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

            height = screen.add_text(1, 1, f"{answer["message"]}({token["total_tokens"]})", (255, 255, 255), screen.get_size()[0] - 2)
            screen.add_rect(0, 0, screen.get_size()[0], height + 2, (255, 128, 255), True)
            screen.render(True)
            print()

            # 处理记忆增强
            if "iptmem" in answer and isinstance(answer["iptmem"], list):
                memory = boost_memory_importance(memory, answer["iptmem"], boost_amount=0.5)
                # print(CFVI.cli.colorize_text(f"已增强记忆 {answer['iptmem']} 的重要性", (128, 255, 128)))

            # 添加新记忆
            if answer.get("remember", "") != "":
                # importance_boost = 0.5 if "iptmem" in answer else 0  # 如果同时有iptmem，给新记忆额外重要性
                importance_boost = 0
                memory = add_to_memory(memory, answer["remember"], importance_boost)
                save_json_file(mem_path, memory)

            if answer.get("cmd", "") == "":
                break

            print(CFVI.cli.colorize_text(f"{answer.get('cmd_dir', '')}>{answer["cmd"]}", (64, 64, 64)))
            result = cmd(answer["cmd"].replace("§file§", answer.get("file", "")), answer.get("file", ""))
            result, token = ai.chat(result)

        except Exception as e:
            print(CFVI.cli.colorize_text(f"出错了喵：{str(e)}", (255, 0, 0)))
            print(CFVI.cli.colorize_text(f"{str(result)}", (64, 64, 64)))
            break
