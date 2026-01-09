"""
高级白名单插件
支持临时会话、好友私聊、群聊的独立控制和全局白名单
"""

import astrbot.api.star as star
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.message_type import MessageType
from sys import maxsize
from datetime import datetime, date
import time


@register(
    "advanced_whitelist_blacklist",
    "AstrBot",
    "高级白名单插件，支持临时会话、好友私聊、群聊的独立控制和全局白名单",
    "1.0.0",
    "https://github.com/AstrBotDevs/AstrBot"
)
class AdvancedWhitelistPlugin(Star):
    """高级白名单插件"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.context = context
        self.config = config
        if self.config is None:
            # 如果没有传入 config，尝试从 metadata 获取
            from astrbot.core.star import star_registry
            for star in star_registry:
                if star.name == "advanced_whitelist_blacklist":
                    self.config = star.config
                    break
        if self.config is None:
            logger.warning("高级白名单插件未找到配置，将使用默认配置")
            from astrbot.core.config.astrbot_config import AstrBotConfig
            self.config = AstrBotConfig({}, {})
        
        # 获取平台ID列表（用于匹配）
        self.platform_ids = self._get_platform_ids()
        # 频率控制：记录每天每个会话的第一次反馈时间
        # key: unified_msg_origin, value: date (今天的日期)
        self._daily_feedback_cache = {}
        logger.info(f"高级白名单插件已加载，检测到平台ID: {self.platform_ids}")
    
    def _get_platform_ids(self) -> list:
        """获取平台ID列表，优先从配置读取，否则使用用户配置的列表"""
        # 首先尝试从配置中读取
        try:
            platform_configs = self.context.get_config().get("platform", [])
            platform_ids = []
            for platform in platform_configs:
                if platform.get("enable", False) and platform.get("id"):
                    platform_ids.append(platform["id"])
            if platform_ids:
                logger.info(f"从配置中读取到平台ID: {platform_ids}")
                return platform_ids
        except Exception as e:
            logger.debug(f"无法从配置中读取平台ID: {e}")
        
        # 如果无法读取，使用用户配置的列表
        user_platform_ids = self.config.get("platform_ids", [])
        if user_platform_ids:
            logger.info(f"使用用户配置的平台ID: {user_platform_ids}")
            return user_platform_ids
        
        # 如果都没有，返回空列表（匹配时只能匹配完整格式）
        logger.warning("未找到平台ID配置，纯数字输入可能无法正确匹配。请在插件配置中填入 platform_ids")
        return []

    def _match_whitelist(self, whitelist: list, user_id: str = None, group_id: str = None, 
                        unified_msg_origin: str = None) -> bool:
        """检查是否在白名单中，支持多种格式匹配
        
        匹配逻辑：
        1. 直接匹配完整的 unified_msg_origin（如 qq:FriendMessage:12345678）
        2. 匹配用户ID（QQ号），适用于私聊
        3. 匹配群ID（QQ群号），适用于群聊
        4. 匹配带前缀的格式（如 qq:FriendMessage:12345678），提取ID部分匹配
        5. 对于纯数字输入，从 unified_msg_origin 中解析 platform_id 和 message_type，然后匹配
        """
        if not whitelist:
            return False
        
        user_id = str(user_id).strip() if user_id else None
        group_id = str(group_id).strip() if group_id else None
        
        # 解析 unified_msg_origin 获取平台ID和消息类型
        platform_id = None
        message_type = None
        session_id_from_origin = None
        if unified_msg_origin:
            try:
                parts = unified_msg_origin.split(":")
                if len(parts) >= 3:
                    platform_id = parts[0]
                    message_type = parts[1]
                    session_id_from_origin = parts[2]
            except Exception:
                pass
        
        for item in whitelist:
            item = str(item).strip()
            if not item:
                continue
            
            # 1. 直接匹配完整会话ID
            if unified_msg_origin and item == unified_msg_origin:
                return True
            
            # 2. 匹配用户ID（QQ号）- 适用于私聊
            if user_id and item == user_id:
                return True
            
            # 3. 匹配群ID（QQ群号）- 适用于群聊
            if group_id and item == group_id:
                return True
            
            # 4. 匹配带前缀的格式（如 qq:FriendMessage:12345678）
            if ":" in item:
                try:
                    parts = item.split(":")
                    if len(parts) >= 3:
                        # 提取ID部分进行匹配
                        item_id = parts[-1]
                        # 匹配用户ID
                        if user_id and item_id == user_id:
                            return True
                        # 匹配群ID
                        if group_id and item_id == group_id:
                            return True
                        # 如果 session_id_from_origin 存在，也尝试匹配
                        if session_id_from_origin and item_id == session_id_from_origin:
                            return True
                except Exception:
                    pass
            else:
                # 5. 纯数字输入，直接匹配 session_id、user_id 和 group_id
                # unified_msg_origin 格式为 platform_id:message_type:session_id
                # 对于私聊，session_id 通常是用户ID
                # 对于群聊，session_id 可能是群号，也可能是 user_id_group_id（如果 unique_session 开启）
                # 因此我们需要同时匹配 user_id、group_id 和 session_id_from_origin
                # 这样无论用户输入的是QQ号还是群号，都能正确匹配
                if session_id_from_origin and item == session_id_from_origin:
                    return True
                # 匹配 user_id（适用于私聊，或者 unique_session 开启时的群聊）
                if user_id and item == user_id:
                    return True
                # 匹配 group_id（适用于群聊，即使 unique_session 开启，group_id 也是独立的）
                if group_id and item == group_id:
                    return True
        
        return False

    def _check_global_whitelist(self, event: AstrMessageEvent) -> bool:
        """检查是否在全局白名单中"""
        global_whitelist = self.config.get("global_whitelist", [])
        if not global_whitelist:
            return False
        
        return self._match_whitelist(
            global_whitelist,
            user_id=event.get_sender_id(),
            group_id=event.get_group_id(),
            unified_msg_origin=event.unified_msg_origin
        )

    def _is_historical_message(self, event: AstrMessageEvent) -> bool:
        """检查消息是否为历史消息
        
        如果消息时间戳与当前时间相差超过5分钟，认为是历史消息
        
        返回:
            True: 是历史消息
            False: 是新消息
        """
        try:
            # 获取消息时间戳
            message_timestamp = getattr(event.message_obj, "timestamp", None)
            if message_timestamp is None:
                # 如果没有时间戳，尝试从 raw_message 中获取
                raw_msg = getattr(event.message_obj, "raw_message", None)
                if raw_msg and isinstance(raw_msg, dict):
                    message_timestamp = raw_msg.get("time")
                
            if message_timestamp is None:
                # 如果仍然无法获取时间戳，假设是新消息
                logger.debug(f"[历史消息检查] 无法获取消息时间戳，假设为新消息")
                return False
            
            # 获取当前时间戳
            current_timestamp = int(time.time())
            
            # 计算时间差（秒）
            time_diff = current_timestamp - int(message_timestamp)
            
            # 如果时间差超过5分钟（300秒），认为是历史消息
            if time_diff > 300:
                logger.debug(f"[历史消息检查] 检测到历史消息，时间差: {time_diff}秒，消息时间戳: {message_timestamp}, 当前时间戳: {current_timestamp}")
                return True
            
            logger.debug(f"[历史消息检查] 新消息，时间差: {time_diff}秒")
            return False
            
        except Exception as e:
            logger.debug(f"[历史消息检查] 检查历史消息时出错: {e}，假设为新消息")
            return False
    
    def _should_send_feedback(self, event: AstrMessageEvent) -> bool:
        """检查是否应该发送反馈（每天第一次，且仅限新消息）
        
        返回:
            True: 应该发送反馈（今天第一次且是新消息）
            False: 不应该发送反馈（今天已经发送过，或者是历史消息）
        """
        # 首先检查是否为历史消息
        if self._is_historical_message(event):
            logger.debug(f"[频率控制] 消息是历史消息，不发送反馈")
            return False
        
        today = date.today()
        umo = event.unified_msg_origin
        
        # 检查今天是否已经发送过反馈
        cached_date = self._daily_feedback_cache.get(umo)
        if cached_date == today:
            logger.debug(f"[频率控制] 会话 {umo} 今天已发送过反馈，跳过")
            return False  # 今天已经发送过，不重复发送
        
        # 如果缓存中的日期不是今天（可能是旧日期或不存在），需要更新
        # 同时清理旧缓存条目（避免内存泄漏）
        if cached_date is not None and cached_date != today:
            # 清理旧的缓存条目
            if umo in self._daily_feedback_cache:
                del self._daily_feedback_cache[umo]
                logger.debug(f"[频率控制] 清理过期缓存条目: {umo} (日期: {cached_date})")
        
        logger.debug(f"[频率控制] 会话 {umo} 今天第一次且是新消息，将发送反馈（上次反馈日期: {cached_date}）")
        return True
    
    def _mark_feedback_sent(self, event: AstrMessageEvent):
        """标记已发送反馈（只有在实际发送反馈消息时才调用）"""
        today = date.today()
        umo = event.unified_msg_origin
        self._daily_feedback_cache[umo] = today
        logger.debug(f"[频率控制] 已标记会话 {umo} 今天已发送反馈")
    
    def _is_request_event(self, event: AstrMessageEvent) -> bool:
        """判断是否为请求事件（好友申请、群聊邀请等）
        
        请求事件的特征：
        1. raw_message中的post_type是"request"
        2. message_str为空字符串
        """
        raw_msg = getattr(event.message_obj, "raw_message", None)
        if raw_msg and isinstance(raw_msg, dict):
            post_type = raw_msg.get("post_type", "")
            if post_type == "request":
                return True
        
        # 如果message_str为空，且不是正常的消息，可能是请求事件
        if not event.message_str or event.message_str.strip() == "":
            raw_msg = getattr(event.message_obj, "raw_message", None)
            if raw_msg and isinstance(raw_msg, dict):
                post_type = raw_msg.get("post_type", "")
                if post_type == "request":
                    return True
        
        return False
    
    def _is_temporary_session(self, event: AstrMessageEvent) -> bool:
        """判断是否为临时会话的私聊消息
        
        排除请求事件（好友申请、群聊邀请），只识别临时会话的私聊消息。
        
        对于QQ平台（aiocqhttp），临时会话的识别方式：
        1. 消息类型为OTHER_MESSAGE（排除请求事件）
        2. 或者消息类型为FRIEND_MESSAGE，但raw_message中的sub_type不是"friend"（排除请求事件）
        """
        # 先排除请求事件（好友申请、群聊邀请）
        if self._is_request_event(event):
            logger.debug(f"[临时会话识别] 检测到请求事件，跳过: {event.unified_msg_origin}")
            return False
        
        message_type = event.get_message_type()
        
        # 如果消息类型是OTHER_MESSAGE，且不是请求事件，可能是临时会话
        if message_type == MessageType.OTHER_MESSAGE:
            # 再次确认不是请求事件
            if not self._is_request_event(event):
                return True
        
        # 对于QQ平台（aiocqhttp），检查raw_message中的sub_type
        if event.get_platform_name() == "aiocqhttp" and message_type == MessageType.FRIEND_MESSAGE:
            raw_msg = getattr(event.message_obj, "raw_message", None)
            if raw_msg and isinstance(raw_msg, dict):
                post_type = raw_msg.get("post_type", "")
                # 排除请求事件
                if post_type == "request":
                    return False
                
                sub_type = raw_msg.get("sub_type", "")
                message_type_str = raw_msg.get("message_type", "")
                # 如果是private消息且sub_type存在且不是"friend"，可能是临时会话
                if message_type_str == "private":
                    if sub_type and sub_type != "friend":
                        logger.debug(f"[临时会话识别] 检测到临时会话，sub_type: {sub_type}, 会话: {event.unified_msg_origin}")
                        return True
                    # 如果sub_type为空或"friend"，但session_id格式可能是临时会话格式
                    # QQ临时会话的session_id通常是群号，而不是QQ号
                    session_id = event.get_session_id()
                    # 如果session_id是数字且长度较长（可能是群号），可能是临时会话
                    # 但更准确的方式是检查sub_type
                    if not sub_type or sub_type == "":
                        logger.debug(f"[临时会话识别] private消息但sub_type为空，可能是临时会话，会话: {event.unified_msg_origin}")
        
        return False
    
    def _check_temp_session(self, event: AstrMessageEvent) -> bool:
        """检查临时会话控制
        
        返回:
            True: 允许通过
            False: 已阻止
        """
        enable_control = self.config.get("enable_temp_session_control", False)
        logger.debug(f"[临时会话检查] 控制开关: {enable_control}, 会话: {event.unified_msg_origin}")
        
        if not enable_control:
            logger.debug(f"[临时会话检查] 控制未启用，允许通过")
            return True  # 未启用控制，允许通过
        
        # 临时会话控制仅作为开关，直接阻止
        if self.config.get("log_blocked_messages", True):
            logger.info(f"临时会话 {event.unified_msg_origin} 被阻止（临时会话控制已启用）")
        
        # 检查是否应该发送反馈（每天第一次，且仅限新消息）
        should_send = self._should_send_feedback(event)
        
        if should_send:
            # 每天第一次且是新消息：发送反馈消息
            logger.debug(f"[临时会话检查] 发送反馈消息（每天第一次且是新消息）")
            # 标记已发送反馈
            self._mark_feedback_sent(event)
            # 设置消息结果并停止事件
            event.set_result(
                MessageEventResult().message("要经过姐姐同意哦").stop_event()
            )
        else:
            # 后续消息或历史消息：静默阻止
            is_historical = self._is_historical_message(event)
            if is_historical:
                logger.debug(f"[临时会话检查] 历史消息，静默阻止（不发送反馈）")
            else:
                logger.debug(f"[临时会话检查] 今天已发送过反馈，静默阻止")
            event.stop_event()
        
        return False

    def _check_friend_message(self, event: AstrMessageEvent) -> bool:
        """检查好友私聊白名单
        
        返回:
            True: 允许通过
            False: 已阻止
        """
        enable_whitelist = self.config.get("enable_friend_message_whitelist", False)
        logger.debug(f"[好友私聊检查] 白名单开关: {enable_whitelist}, 会话: {event.unified_msg_origin}, 用户ID: {event.get_sender_id()}")
        
        if not enable_whitelist:
            logger.debug(f"[好友私聊检查] 白名单未启用，允许通过")
            return True  # 未启用白名单，允许通过
        
        whitelist = self.config.get("friend_message_whitelist", [])
        logger.debug(f"[好友私聊检查] 白名单内容: {whitelist}")
        
        if not whitelist:
            # 白名单为空，允许通过
            logger.debug(f"[好友私聊检查] 白名单为空，允许通过")
            return True
        
        # 检查是否在白名单中
        is_in_whitelist = self._match_whitelist(
            whitelist,
            user_id=event.get_sender_id(),
            unified_msg_origin=event.unified_msg_origin
        )
        logger.debug(f"[好友私聊检查] 是否在白名单中: {is_in_whitelist}")
        
        if is_in_whitelist:
            return True
        
        # 不在白名单中
        if self.config.get("log_blocked_messages", True):
            logger.info(f"好友私聊 {event.unified_msg_origin} 不在白名单中，已阻止")
        
        # 检查是否应该发送反馈（每天第一次，且仅限新消息）
        should_send = self._should_send_feedback(event)
        
        if should_send:
            # 每天第一次且是新消息：发送反馈消息
            logger.debug(f"[好友私聊检查] 发送反馈消息（每天第一次且是新消息）")
            # 标记已发送反馈
            self._mark_feedback_sent(event)
            # 设置消息结果并停止事件
            event.set_result(
                MessageEventResult().message("要先经过姐姐同意哦").stop_event()
            )
        else:
            # 后续消息或历史消息：静默阻止
            is_historical = self._is_historical_message(event)
            if is_historical:
                logger.debug(f"[好友私聊检查] 历史消息，静默阻止（不发送反馈）")
            else:
                logger.debug(f"[好友私聊检查] 今天已发送过反馈，静默阻止")
            event.stop_event()
        
        return False

    def _check_group_message(self, event: AstrMessageEvent) -> bool:
        """检查群聊白名单"""
        if not self.config.get("enable_group_message_whitelist", False):
            return True  # 未启用白名单，允许通过
        
        whitelist = self.config.get("group_message_whitelist", [])
        if not whitelist:
            # 白名单为空，允许通过
            return True
        
        # 检查是否在白名单中
        if self._match_whitelist(
            whitelist,
            user_id=event.get_sender_id(),
            group_id=event.get_group_id(),
            unified_msg_origin=event.unified_msg_origin
        ):
            return True
        
        # 不在白名单中
        if self.config.get("log_blocked_messages", True):
            logger.info(f"群聊会话 {event.unified_msg_origin} 不在白名单中，已阻止")
        
        # 群聊不发送消息，静默阻止
        event.stop_event()
        return False

    @filter.event_message_type(filter.EventMessageType.ALL, priority=maxsize)
    async def check_whitelist(self, event: AstrMessageEvent):
        """检查白名单"""
        message_type = event.get_message_type()
        unified_msg_origin = event.unified_msg_origin
        
        logger.debug(f"[白名单检查] 消息类型: {message_type}, 会话: {unified_msg_origin}")
        
        # 首先检查全局白名单（如果在全局白名单中，直接通过）
        if self._check_global_whitelist(event):
            logger.debug(f"[白名单检查] {unified_msg_origin} 在全局白名单中，允许通过")
            return  # 全局白名单，直接通过
        
        # 检查是否为请求事件（好友申请、群聊邀请等），请求事件独立放行，不受白名单限制
        if self._is_request_event(event):
            logger.debug(f"[白名单检查] 检测到请求事件（好友申请/群聊邀请），独立放行: {unified_msg_origin}")
            return  # 请求事件独立放行，不受白名单限制
        
        # 检查是否为临时会话（需要特殊处理，因为QQ的临时会话可能是FRIEND_MESSAGE类型）
        is_temp_session = self._is_temporary_session(event)
        
        if is_temp_session:
            # 临时会话
            logger.debug(f"[白名单检查] 检测到临时会话: {unified_msg_origin}")
            if not self._check_temp_session(event):
                logger.debug(f"[白名单检查] 临时会话被阻止: {unified_msg_origin}")
                # _check_temp_session 内部已经处理了 stop_event，这里直接返回
                return
        elif message_type == MessageType.FRIEND_MESSAGE:
            # 好友私聊（非临时会话）
            logger.debug(f"[白名单检查] 检测到好友私聊: {unified_msg_origin}")
            if not self._check_friend_message(event):
                logger.debug(f"[白名单检查] 好友私聊被阻止: {unified_msg_origin}")
                # _check_friend_message 内部已经处理了 stop_event，这里直接返回
                return
        elif message_type == MessageType.GROUP_MESSAGE:
            # 群聊
            logger.debug(f"[白名单检查] 检测到群聊: {unified_msg_origin}")
            if not self._check_group_message(event):
                logger.debug(f"[白名单检查] 群聊被阻止: {unified_msg_origin}")
                # _check_group_message 内部已经处理了 stop_event，这里直接返回
                return
        elif message_type == MessageType.OTHER_MESSAGE:
            # 其他类型的临时会话
            logger.debug(f"[白名单检查] 检测到其他类型临时会话: {unified_msg_origin}")
            if not self._check_temp_session(event):
                logger.debug(f"[白名单检查] 临时会话被阻止: {unified_msg_origin}")
                return
        else:
            logger.debug(f"[白名单检查] 未知消息类型: {message_type}, 会话: {unified_msg_origin}")

    @filter.command_group("awb")
    def awb(self):
        """高级白名单管理命令组"""
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @awb.command("add_wl")
    async def add_whitelist(self, event: AstrMessageEvent, list_type: str = "", qq_or_group_id: str = ""):
        """添加白名单。awb add_wl <类型> <QQ号或群号>"""
        if not list_type or not qq_or_group_id:
            event.set_result(MessageEventResult().message(
                "使用方法: /awb add_wl <类型> <QQ号或群号>\n"
                "类型: friend(好友私聊), group(群聊), global(全局)\n"
                "示例: /awb add_wl friend 12345678\n"
                "示例: /awb add_wl group 123456789"
            ))
            return
        
        list_type = list_type.lower()
        config_key_map = {
            "friend": "friend_message_whitelist",
            "group": "group_message_whitelist",
            "global": "global_whitelist"
        }
        
        if list_type not in config_key_map:
            event.set_result(MessageEventResult().message(
                "类型错误！支持的类型: friend, group, global"
            ))
            return
        
        config_key = config_key_map[list_type]
        whitelist = self.config.get(config_key, [])
        
        # 去除空格
        qq_or_group_id = qq_or_group_id.strip()
        
        if qq_or_group_id not in whitelist:
            whitelist.append(qq_or_group_id)
            self.config[config_key] = whitelist
            self.config.save_config()
            event.set_result(MessageEventResult().message(
                f"已添加到{list_type}白名单: {qq_or_group_id}\n"
                f"（可直接输入QQ号或群号，系统会自动匹配不同平台的格式）"
            ))
        else:
            event.set_result(MessageEventResult().message(f"{qq_or_group_id} 已在{list_type}白名单中"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @awb.command("del_wl")
    async def del_whitelist(self, event: AstrMessageEvent, list_type: str = "", qq_or_group_id: str = ""):
        """删除白名单。awb del_wl <类型> <QQ号或群号>"""
        if not list_type or not qq_or_group_id:
            event.set_result(MessageEventResult().message(
                "使用方法: /awb del_wl <类型> <QQ号或群号>\n"
                "类型: friend(好友私聊), group(群聊), global(全局)"
            ))
            return
        
        list_type = list_type.lower()
        config_key_map = {
            "friend": "friend_message_whitelist",
            "group": "group_message_whitelist",
            "global": "global_whitelist"
        }
        
        if list_type not in config_key_map:
            event.set_result(MessageEventResult().message(
                "类型错误！支持的类型: friend, group, global"
            ))
            return
        
        config_key = config_key_map[list_type]
        whitelist = self.config.get(config_key, [])
        
        qq_or_group_id = qq_or_group_id.strip()
        
        try:
            whitelist.remove(qq_or_group_id)
            self.config[config_key] = whitelist
            self.config.save_config()
            event.set_result(MessageEventResult().message(f"已从{list_type}白名单删除: {qq_or_group_id}"))
        except ValueError:
            event.set_result(MessageEventResult().message(f"{qq_or_group_id} 不在{list_type}白名单中"))

    @awb.command("list")
    async def list_all(self, event: AstrMessageEvent, list_type: str = ""):
        """查看白名单。awb list [类型]"""
        if not list_type:
            # 显示所有列表
            msg = "=== 高级白名单列表 ===\n\n"
            
            # 临时会话
            msg += "【临时会话】\n"
            msg += f"控制开关: {'开启（所有临时会话将被阻止）' if self.config.get('enable_temp_session_control', False) else '关闭'}\n\n"
            
            # 好友私聊
            msg += "【好友私聊】\n"
            msg += f"白名单开关: {'开启' if self.config.get('enable_friend_message_whitelist', False) else '关闭'}\n"
            friend_wl = self.config.get("friend_message_whitelist", [])
            msg += f"白名单({len(friend_wl)}): {', '.join(friend_wl[:10])}{' ...' if len(friend_wl) > 10 else ''}\n\n"
            
            # 群聊
            msg += "【群聊】\n"
            msg += f"白名单开关: {'开启' if self.config.get('enable_group_message_whitelist', False) else '关闭'}\n"
            group_wl = self.config.get("group_message_whitelist", [])
            msg += f"白名单({len(group_wl)}): {', '.join(group_wl[:10])}{' ...' if len(group_wl) > 10 else ''}\n\n"
            
            # 全局
            msg += "【全局】\n"
            global_wl = self.config.get("global_whitelist", [])
            msg += f"白名单({len(global_wl)}): {', '.join(global_wl[:10])}{' ...' if len(global_wl) > 10 else ''}\n"
            
            event.set_result(MessageEventResult().message(msg).use_t2i(False))
            return
        
        list_type = list_type.lower()
        type_map = {
            "friend": ("好友私聊", "friend_message_whitelist"),
            "group": ("群聊", "group_message_whitelist"),
            "global": ("全局", "global_whitelist")
        }
        
        if list_type not in type_map:
            event.set_result(MessageEventResult().message(
                "类型错误！支持的类型: friend, group, global"
            ))
            return
        
        type_name, wl_key = type_map[list_type]
        whitelist = self.config.get(wl_key, [])
        
        msg = f"=== {type_name}白名单 ===\n\n"
        msg += f"白名单({len(whitelist)}):\n"
        if whitelist:
            for item in whitelist:
                msg += f"  - {item}\n"
        else:
            msg += "  (空)\n"
        
        event.set_result(MessageEventResult().message(msg).use_t2i(False))

    async def terminate(self):
        """插件停用时调用"""
        logger.info("高级白名单插件已卸载")
