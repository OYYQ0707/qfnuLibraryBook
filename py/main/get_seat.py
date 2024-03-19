import asyncio
import concurrent.futures
import datetime
import logging
import os
import random
import sys
import time

import requests
import yaml
from telegram import Bot

from get_bearer_token import get_bearer_token
from get_info import get_date, get_seat_info, get_segment, get_build_id, encrypt, get_member_seat

# 配置日志
logger = logging.getLogger("httpx")
logger.setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL_GET_SEAT = "http://libyy.qfnu.edu.cn/api/Seat/confirm"
URL_CHECK_OUT = "http://libyy.qfnu.edu.cn/api/Space/checkout"
URL_CANCEL_SEAT = "http://libyy.qfnu.edu.cn/api/Space/cancel"

# 配置文件
CHANNEL_ID = ""
TELEGRAM_BOT_TOKEN = ""
MODE = ""
CLASSROOMS_NAME = ""
SEAT_ID = ""
DATE = ""
USERNAME = ""
PASSWORD = ""
GITHUB = ""
BARK_URL = ""
BARK_EXTRA = ""


# 读取YAML配置文件并设置全局变量
def read_config_from_yaml():
    global CHANNEL_ID, TELEGRAM_BOT_TOKEN, \
        CLASSROOMS_NAME, MODE, SEAT_ID, DATE, USERNAME, PASSWORD, GITHUB, BARK_EXTRA, BARK_URL
    current_dir = os.path.dirname(os.path.abspath(__file__))  # 获取当前文件所在的目录的绝对路径
    config_file_path = os.path.join(current_dir, 'config.yml')  # 将文件名与目录路径拼接起来
    with open(config_file_path, 'r') as yaml_file:
        config = yaml.safe_load(yaml_file)
        CHANNEL_ID = config.get('CHANNEL_ID', '')
        TELEGRAM_BOT_TOKEN = config.get('TELEGRAM_BOT_TOKEN', '')
        CLASSROOMS_NAME = config.get("CLASSROOMS_NAME", [])
        MODE = config.get("MODE", "")
        SEAT_ID = config.get("SEAT_ID", "")
        DATE = config.get("DATE", "")
        USERNAME = config.get('USERNAME', '')
        PASSWORD = config.get('PASSWORD', '')
        GITHUB = config.get("GITHUB", "")
        BARK_URL = config.get("BARK_URL", "")
        BARK_EXTRA = config.get("BARK_EXTRA", "")


# 在代码的顶部定义全局变量
FLAG = False
SEAT_RESULT = {}
MESSAGE = ""
AUTH_TOKEN = ""
NEW_DATE = ""
TOKEN_TIMESTAMP = None
TOKEN_EXPIRY_DELTA = datetime.timedelta(hours=1, minutes=30)

# 配置常量
EXCLUDE_ID = {'7443', '7448', '7453', '7458', '7463', '7468', '7473', '7478', '7483', '7488', '7493', '7498', '7503',
              '7508', '7513', '7518', '7572', '7575', '7578', '7581', '7584', '7587', '7590', '7785', '7788', '7791',
              '7794', '7797', '7800', '7803', '7806', '7291', '7296', '7301', '7306', '7311', '7316', '7321', '7326',
              '7331', '7336', '7341', '7346', '7351', '7356', '7361', '7366', '7369', '7372', '7375', '7378', '7381',
              '7384', '7387', '7390', '7417', '7420', '7423', '7426', '7429', '7432', '7435', '7438', '7115', '7120',
              '7125', '7130', '7135', '7140', '7145', '7150', '7155', '7160', '7165', '7170', '7175', '7180', '7185',
              '7190', '7241', '7244', '7247', '7250', '7253', '7256', '7259', '7262', '7761', '7764', '7767', '7770',
              '7773', '7776', '7779', '7782'}

MAX_RETRIES = 200  # 最大重试次数


# 打印变量
def print_variables():
    variables = {
        "CHANNEL_ID": CHANNEL_ID,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "MODE": MODE,
        "CLASSROOMS_NAME": CLASSROOMS_NAME,
        "SEAT_ID": SEAT_ID,
        "USERNAME": USERNAME,
        "PASSWORD": PASSWORD,
        "GITHUB": GITHUB,
        "BARK_URL": BARK_URL,
        "BARK_EXTRA": BARK_EXTRA
    }
    for var_name, var_value in variables.items():
        logger.info(f"{var_name}: {var_value} - {type(var_value)}")


# post 请求
def send_post_request_and_save_response(url, data, headers):
    global MESSAGE
    retries = 0
    while retries < MAX_RETRIES:
        try:
            response = requests.post(url, json=data, headers=headers, timeout=60)
            response.raise_for_status()
            response_data = response.json()
            return response_data
        except requests.exceptions.Timeout:
            logger.error("请求超时，正在重试...")
            retries += 1
        except Exception as e:
            logger.error(f"request请求异常: {str(e)}")
            retries += 1
    logger.error("超过最大重试次数,请求失败。")
    MESSAGE += "\n超过最大重试次数,请求失败。"
    send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
    asyncio.run(send_seat_result_to_channel())
    sys.exit()


# get 请求
def send_get_request(url):
    try:
        response = requests.get(url)
        # 检查响应状态码是否为200
        if response.status_code == 200:
            logger.info("成功推送消息到 Bark")
            # 返回响应内容
            return response.text
        else:
            logger.error(f"推送到 Bark 的 GET请求失败，状态码：{response.status_code}")
            return None
    except requests.exceptions.RequestException:
        logger.info("GET请求异常, 你的 BARK 链接不正确")
        return None


async def send_seat_result_to_channel():
    try:
        # 使用 API 令牌初始化您的机器人
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        # logger.info(f"要发送的消息为： {MESSAGE}\n")
        await bot.send_message(chat_id=CHANNEL_ID, text=MESSAGE)
    except Exception as e:
        logger.info(f"发送消息到 Telegram 失败, 可能是没有设置此通知方式，也可能是没有连接到 Telegram")
        return e


def get_auth_token():
    global TOKEN_TIMESTAMP, AUTH_TOKEN
    try:
        # 如果未从配置文件中读取到用户名或密码，则抛出异常
        if not USERNAME or not PASSWORD:
            raise ValueError("未找到用户名或密码")

        # 检查 Token 是否过期
        if TOKEN_TIMESTAMP is None or (datetime.datetime.now() - TOKEN_TIMESTAMP) > TOKEN_EXPIRY_DELTA:
            # Token 过期或尚未获取，重新获取
            name, token = get_bearer_token(USERNAME, PASSWORD)
            logger.info(f"成功获取授权码")
            AUTH_TOKEN = "bearer" + str(token)
            # 更新 Token 的时间戳
            TOKEN_TIMESTAMP = datetime.datetime.now()
        else:
            logger.info("使用现有授权码")
    except Exception as e:
        logger.error(f"获取授权码时发生异常: {str(e)}")
        sys.exit()


# 检查是否存在已经预约的座位
def check_book_seat():
    global MESSAGE, FLAG
    try:
        while not FLAG:
            res = get_member_seat(AUTH_TOKEN)
            for entry in res["data"]["data"]:
                if entry["statusName"] == "预约成功" and DATE == "tomorrow":
                    logger.info("存在已经预约的座位")
                    FLAG = True
                elif entry["statusName"] == "使用中" and DATE == "today":
                    logger.info("存在正在使用的座位")
                    FLAG = True
            time.sleep(1)
    # todo 未遇到此错误
    except KeyError:
        logger.error("数据解析错误")
        sys.exit()


# 状态检测函数
def check_reservation_status(seat_result):
    global FLAG, MESSAGE
    try:
        while not FLAG:
            # 状态信息检测
            if 'msg' in seat_result:
                status = seat_result['msg']
                logger.info(status)
                if status == "当前时段存在预约，不可重复预约!":
                    logger.info("重复预约, 请检查选择的时间段或是否已经成功预约")
                    FLAG = True
                elif status == "预约成功":
                    logger.info("成功预约")
                    seat = seat_result['seat']
                    MESSAGE += f"\n{status}\n 预约的座位是:{seat}"
                    send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
                    asyncio.run(send_seat_result_to_channel())
                    FLAG = True
                elif status == "开放预约时间19:20":
                    logger.info("未到预约时间, 3s 后重试")
                    time.sleep(3)
                elif status == "您尚未登录":
                    logger.info("没有登录，将重新尝试获取 token")
                    get_auth_token()
                elif status == "该空间当前状态不可预约":
                    logger.info("此位置已被预约")
                    if MODE == "2":
                        logger.info("此座位已被预约，请在 config 中修改 SEAT_ID 后重新预约")
                        FLAG = True
                    else:
                        logger.info(f"选定座位已被预约，重新选定")
    # todo 没有出现此错误
    except KeyError:
        logger.error("没有获取到状态信息，token已过期, 重新获取 token")
        get_auth_token()


# 预约函数
def post_to_get_seat(select_id, segment):
    # 原始数据
    origin_data = '{{"seat_id":"{}","segment":"{}"}}'.format(select_id, segment)
    # logger.info(origin_data)

    # 加密数据
    aes_data = encrypt(str(origin_data))
    # aes_data = "test"
    # logger.info(aes_data)

    # 测试解密数据
    # aes = decrypt(aes_data)
    # logger.info(aes)

    # 原始的 post_data
    post_data = {
        "aesjson": aes_data,
    }
    request_headers = {
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "Accept": "application/json, text/plain, */*",
        "lang": "zh",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, "
                      "like Gecko)"
                      "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "Origin": "http://libyy.qfnu.edu.cn",
        "Referer": "http://libyy.qfnu.edu.cn/h5/index.html",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5",
        "Authorization": AUTH_TOKEN
    }
    # 发送POST请求并获取响应
    seat_result = send_post_request_and_save_response(URL_GET_SEAT, post_data, request_headers)
    check_reservation_status(seat_result)


# 随机获取座位
def random_get_seat(data):
    global MESSAGE
    # 随机选择一个字典
    random_dict = random.choice(data)
    # 获取该字典中 'id' 键对应的值
    select_id = random_dict['id']
    # seat_no = random_dict['no']
    # logger.info(f"随机选择的座位为: {select_id} 真实位置: {seat_no}")
    return select_id


# 选座主要逻辑
def select_seat(build_id, segment, nowday):
    # 初始化
    try:
        while not FLAG:
            # 获取座位信息
            data = get_seat_info(build_id, segment, nowday)
            # 优选逻辑
            if MODE == "1":
                new_data = [d for d in data if d['id'] not in EXCLUDE_ID]
                # logger.info(new_data)
                # 检查返回的列表是否为空
                if not new_data:
                    # logger.info("无可用座位, 程序将 1s 后再次获取")
                    time.sleep(1)
                    continue
                else:
                    select_id = random_get_seat(new_data)
                    post_to_get_seat(select_id, segment)
            # 指定逻辑
            elif MODE == "2":
                # logger.info(f"你选定的座位为: {SEAT_ID}")
                post_to_get_seat(SEAT_ID, segment)
            # 默认逻辑
            elif MODE == "3":
                # 检查返回的列表是否为空
                if not data:
                    # logger.info("无可用座位, 程序将 3s 后再次获取")
                    time.sleep(3)
                    continue
                else:
                    select_id = random_get_seat(data)
                    post_to_get_seat(select_id, segment)
            else:
                logger.error(f"未知的模式: {MODE}")

    except KeyboardInterrupt:
        logger.info(f"接收到中断信号，程序将退出。")


# 取消座位预约（慎用！！！）
def cancel_seat(seat_id):
    try:
        post_data = {
            "id": seat_id,
            "authorization": AUTH_TOKEN
        }
        request_headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "lang": "zh",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, "
                          "like Gecko)"
                          "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
            "Origin": "http://libyy.qfnu.edu.cn",
            "Referer": "http://libyy.qfnu.edu.cn/h5/index.html",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5",
            "Authorization": AUTH_TOKEN
        }
        seat_result = send_post_request_and_save_response(URL_CANCEL_SEAT, post_data, request_headers)
        # logger.info(seat_result)
    except KeyError:
        logger.info("数据解析错误")


# 新功能
def rebook_seat_or_checkout():
    global MESSAGE
    try:
        get_auth_token()
        res = get_member_seat(AUTH_TOKEN)
        # logger.info(res)
        if res is not None:
            # 延长半小时，寻找已预约的座位
            if MODE == "5":
                # logger.info("test")
                for item in res["data"]["data"]:
                    if item["statusName"] == "预约开始提醒":
                        ids = item["id"]  # 获取 id
                        space = item["space"]  # 获取 seat_id
                        name_merge = item["nameMerge"]  # 获取名称（nameMerge）
                        name_merge = name_merge.split('-', 1)[-1]
                        build_id = get_build_id(name_merge)
                        segment = get_segment(build_id, NEW_DATE)
                        cancel_seat(ids)
                        post_to_get_seat(space, segment)
                    else:
                        logger.error("没有找到已经预约的座位，你可能没有预约座位")
                        MESSAGE += "\n没有找到已经预约的座位，你可能没有预约座位"
                        send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
                        asyncio.run(send_seat_result_to_channel())
                        sys.exit()
            # 签退，寻找正在使用的座位
            if MODE == "4":
                seat_id = None  # 初始化为None
                for item in res["data"]["data"]:
                    if item["statusName"] == "使用中":
                        seat_id = item["id"]  # 找到使用中的座位
                        # logger.info("test")
                        # logger.info(seat_id)
                        break  # 找到座位后退出循环

                if seat_id is not None:  # 确保 seat_id 不为空
                    post_data = {
                        "id": seat_id,
                        "authorization": AUTH_TOKEN
                    }
                    request_headers = {
                        "Content-Type": "application/json",
                        "Connection": "keep-alive",
                        "Accept": "application/json, text/plain, */*",
                        "lang": "zh",
                        "X-Requested-With": "XMLHttpRequest",
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, "
                                      "like Gecko)"
                                      "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
                        "Origin": "http://libyy.qfnu.edu.cn",
                        "Referer": "http://libyy.qfnu.edu.cn/h5/index.html",
                        "Accept-Encoding": "gzip, deflate",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,pl;q=0.5",
                        "Authorization": AUTH_TOKEN
                    }
                    res = send_post_request_and_save_response(URL_CHECK_OUT, post_data, request_headers)
                    if "msg" in res:
                        status = res["msg"]
                        logger.info(status)
                        if status == "完全离开操作成功":
                            MESSAGE += "\n恭喜签退成功"
                            send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
                            asyncio.run(send_seat_result_to_channel())
                            sys.exit()
                        else:
                            logger.info("已经签退")
                else:
                    logger.error("没有找到正在使用的座位，今天你可能没有预约座位")
                    MESSAGE += "\n没有找到正在使用的座位，今天你可能没有预约座位"
                    send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
                    asyncio.run(send_seat_result_to_channel())
                    sys.exit()
        # todo 没有遇到此错误
        else:
            logger.error("获取数据失败，请检查登录状态")
            sys.exit()

    except KeyError:
        logger.error("返回数据与规则不符，大概率是没有登录")
        get_auth_token()
        rebook_seat_or_checkout()


def process_classroom(classroom_name):
    build_id = get_build_id(classroom_name)
    segment = get_segment(build_id, NEW_DATE)
    select_seat(build_id, segment, NEW_DATE)


# 主函数
def get_info_and_select_seat():
    global AUTH_TOKEN, NEW_DATE, MESSAGE
    try:
        if DATE == "tomorrow":
            while True:
                # 获取当前时间
                current_time = datetime.datetime.now()
                # 如果是 Github Action 环境
                if GITHUB:
                    current_time += datetime.timedelta(hours=8)
                # 设置预约时间为19:20
                reservation_time = current_time.replace(hour=19, minute=20, second=0, microsecond=0)
                # 计算距离预约时间的秒数
                time_difference = (reservation_time - current_time).total_seconds()
                # 打印当前时间和距离预约时间的秒数
                logger.info(f"当前时间: {current_time}")
                logger.info(f"距离预约时间还有: {time_difference} 秒")
                # 如果距离时间过长，自动停止程序
                if time_difference > 1000:
                    logger.info("距离预约时间过长，程序将自动停止。")
                    MESSAGE += "\n距离预约时间过长，程序将自动停止"
                    send_get_request(BARK_URL + MESSAGE + BARK_EXTRA)
                    asyncio.run(send_seat_result_to_channel())
                    sys.exit()
                # 如果距离时间在合适的范围内, 将设置等待时间
                elif 1000 >= time_difference > 300:
                    time.sleep(30)
                elif 300 >= time_difference > 60:
                    time.sleep(5)
                else:
                    break

        # logger.info(CLASSROOMS_NAME)
        NEW_DATE = get_date(DATE)
        get_auth_token()
        # 多线程执行程序
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # 存储所有子线程的 Future 对象
            futures = []
            future_first = executor.submit(check_reservation_status)
            futures.append(future_first)
            future_second = executor.submit(check_book_seat)
            futures.append(future_second)
            # 并发启动多个子线程
            for name in CLASSROOMS_NAME:
                # logger.info(name)
                future_third = executor.submit(process_classroom, name)
                futures.append(future_third)

            # 等待所有子线程完成
            concurrent.futures.wait(futures)

    except KeyboardInterrupt:
        logger.info("主动退出程序，程序将退出。")


if __name__ == "__main__":
    try:
        read_config_from_yaml()
        # print_variables()
        if MODE == "4" or MODE == "5":
            NEW_DATE = get_date(DATE)
            rebook_seat_or_checkout()
        else:
            get_info_and_select_seat()

    except KeyboardInterrupt:
        logger.info("主动退出程序，程序将退出。")
