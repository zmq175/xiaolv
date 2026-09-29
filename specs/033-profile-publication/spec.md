# SPEC-033：人设草稿与不可变发布

状态：Verified（控制面HTTP限定范围）。沿用已确认管理HTTP边界，真实PG；不以内部表查询替代接口行为验证。

GET /admin/api/profile返回version（管理状态并发版本）、draft（无则null）和published（无则null，存在时含发布version和profile）。首次无已发布配置，聊天仍使用启动配置，不能把默认人设当作运行配置回显。

PUT /admin/api/profile/draft提交expected_version和profile；POST /admin/api/profile/publish提交expected_version；POST /admin/api/profile/rollback另带release_version。所有写操作必须登录、Origin、CSRF及Idempotency-Key；正文用BotProfile校验，管理写请求外层strict且禁止额外字段。非法字段422只返回错误位置和类型，不回显输入。GET /admin/api/profile/releases/{version}读取不可变发布快照。

保存草稿仅更新草稿；发布创建新release并切换当前发布指针，保留草稿。回滚复制指定旧release为新的release并切换指针，不修改旧记录、不覆盖现有草稿。每次成功写入推进管理version；发布version独立递增。并发expected_version冲突409。相同幂等键+相同规范化请求返回原结果，不再次执行；同键不同内容或动作409。重试即使当前版本已变化仍返回原操作结果，调用方需GET读取最新状态。

私有草稿和幂等记录放admin schema，公开给聊天读取的release/当前指针放app schema。事务持有单个管理状态行锁至提交，原子保存状态/发布指针/幂等回执。记录只写已发布状态，不伪造运行时采用确认。

- AC1：草稿保存后published仍null，发布后可GET读取对应快照；再改草稿不影响发布。
- AC2：同expected_version并发只有一个成功，另一个409；陈旧请求不覆盖新草稿。
- AC3：重建应用重试同幂等键返回相同结果，键冲突不修改数据。
- AC4：回滚产生新release，旧快照不变，草稿保留；无草稿发布/不存在release拒绝。
- AC5：未登录/缺CSRF不可改，错误配置返回字段位置但不回显资料。

本切片不宣称完成网页编辑或聊天动态采用，随后接线；即时会话撤权独立实施。所有返回version是控制面版本，不等于某聊天进程已生效版本。
