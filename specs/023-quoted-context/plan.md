# 计划

先当前会话两条消息的引用关系失败测试，最小上下文表达；再缺失/重复 ID、被裁剪目标逐项验证。通过 TextRuntime 调用真实 ChatCompletionsModel，仅替换外部 StructuredGenerator，不测试私有上下文构造方法。
