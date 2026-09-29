# SPEC-003：结构化日志编码

状态：Verified（日志编码接口）。2026-09-29用户确认配置与日志公共接口测试边界。

## 公共接口

`format_log(entry: LogEntry) -> str` 和 `parse_log(line: str) -> LogEntry`；LogEntry为冻结dataclass记录，含level、timestamp、source（文件:行号）、event、traceid、spanid、message、fields。时间要求带时区、按毫秒输出；解析后时间保留格式中的毫秒精度。__msg为最后一个字段且使用单等号。业务logger接线与OpenTelemetry传播后续切片实现，本切片先保证编解码和防伪造行。

## 验收条件

- AC-001：用户格式示例逐字一致，基础字段traceid、spanid、schema_version=1在前，业务字段按名排序，__msg最后。
- AC-002：解析可还原事件、正文、字段及时间；值可包含等号。
- AC-003：反斜杠、竖线、换行、回车统一转义，解析仅单次解码，正文中的字面转义不二次执行，结果只占一行。
- AC-004：字段名仅小写字母/数字/下划线，禁止业务字段覆盖保留字段。非法头部、事件、trace/span、无时区时间在编码前抛ValueError。
- AC-005：解析拒绝错误schema版本、重复字段、缺基础字段、非法转义、不在最后的__msg及原始换行。

## 范围

纯标准库，不接日志采集服务，不自动记录聊天原文；调用方负责只传业务摘要。事件/字段名称为开发者定义，正文不得拼接进头部。输出时区保留输入偏移；调用方logger后续统一配置时区。
