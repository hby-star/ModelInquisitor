# 下一步开发建议

本文档记录 ModelInquisitor 后续开发建议。第三方 BPMN 到 mCRL2 转译器应保持
不变，后续改进应集中在独立的检查器层。

## 近期优先级

### 1. 增加端到端集成测试

当前项目已经可以在本地运行真实 mCRL2 验证链路。下一步应将这一能力固化为
自动化集成测试。

建议行为：

- 检测 `mcrl22lps`、`lps2pbes`、`pbes2bool` 是否可用；
- 如果工具缺失，则跳过该集成测试；
- 如果工具存在，则使用 `VerificationRunner.verify()` 运行
  `tests/input/spec.bpmn` 和 `tests/input/spec.mcrl2`；
- 断言所有 Claims 均通过。

这样可以保护 parser、strategy、generator、runner 和 CLI 的后续重构，避免引入
回归问题。

### 2. 增加负例转译样例

当前测试主要证明“正确转译可以通过”。作为转译检查器，还需要证明它能够捕获
错误转译。

可选负例：

- 删除或重命名某个 Claim 会引用的 mCRL2 action；
- 破坏某个 message communication action；
- 删除某个 end event action；
- 调整动作顺序，使其违反 causality Claim。

测试应断言至少一个 Claim 失败，或产生明确的模型/公式错误。

这一步很关键，因为转译检查器不仅要能接受正确结果，也必须能识别错误结果。

## 推荐新增 Claims

### 1. Action Preservation Claim

目标：确保 BPMN 中的重要可观察节点没有在转译过程中丢失。

对选定的每个 BPMN 可观察节点，生成一个 Claim，检查其对应的 mCRL2 action
是否可达：

```text
<true* . action>true
```

建议初始范围：

- 普通任务节点；
- message send/receive task，映射到 communicated action 后检查；
- end event；
- boundary event 和 intermediate event 可在命名规则稳定后再纳入。

这类 Claim 是非常高收益的转译完整性 smoke test。

### 2. Message Synchronization Claim

目标：验证每条 BPMN `messageFlow` 都被转译为 mCRL2 中的同步通信。

对每条 message flow，使用命名策略推导：

- send action：`s_msg`；
- receive action：`r_msg`；
- communicated action：`c_msg`。

推荐检查：

```text
<true* . c_msg>true
```

如果转译器通过 `allow` 隐藏原始通信端点，还可以检查：

```text
[true* . s_msg]false
[true* . r_msg]false
```

这可以捕获通信规则缺失、`comm` 声明错误，或原始 send/receive 动作意外暴露等问题。

### 3. Exclusive Branch Reachability Claim

当前 mutex Claim 检查的是两个排他分支不能同时发生，但它不能证明每个分支本身
都是可达的。

建议为每条 exclusive branch 的首个可观察动作增加可达性 Claim：

```text
<true* . branch_action>true
```

两类 Claim 配合后可以形成互补：

- branch reachability 检查每个分支是否被保留；
- mutex 检查分支之间是否仍然保持互斥。

### 4. Parallel Branch Preservation Claim

目标：验证 parallel gateway 的各个并行分支没有在转译中丢失。

对每个 parallel split，查找每条分支中的首个可观察动作，并检查其可达：

```text
<true* . branch_action>true
```

这可以捕获并行分支生成缺失或分支连接错误。

### 5. Parallel Join Synchronization Claim

当前第三方命名策略已经知道 parallel gateway 的同步动作，例如：

- `c_start_gw_N`；
- `c_sync_join_N`。

可考虑检查：

```text
<true* . c_start_gw_N>true
<true* . c_sync_join_N>true
[(!branch_action)* . c_sync_join_N]false
```

建议在 parallel branch preservation 稳定后，再实现这类更强的同步 Claim。

## Runner 与工具链改进

### 1. 明确中间产物生命周期

当前 runner 中存在 `keep_artifacts` 参数，但中间产物清理行为尚未完整实现。

建议语义：

- 如果用户提供 `--work-dir`，则保留该目录中的产物；
- 如果没有提供工作目录，则使用临时目录；
- 如确有需要，再增加 `--keep-artifacts` 参数用于保留默认产物。

### 2. 解析 mCRL2 Action Alphabet

当前检查器主要根据 BPMN 和命名策略推导 action 名称，并没有从 mCRL2 源码中确认
这些 action 是否真实声明。

建议增加轻量级 mCRL2 action parser，用于提取 `act` 声明。

收益：

- 在调用 `lps2pbes` 之前发现缺失 action；
- 改善公式错误诊断；
- 支持更完整的形式化接口：

```text
E(M_bpmn, Code_mcrl2) -> Claims[]
```

### 3. 改进公式参数处理

当前公式默认使用：

```text
exists oid: OrderId. action(oid)
```

这与当前样例兼容，但不够通用。

后续可改进为：

- 从 mCRL2 action alphabet 中推断 action 参数个数和类型；
- 对无参数 action 生成无参数公式；
- 支持多个参数的 action。

## BPMN 覆盖范围扩展

可考虑逐步扩展 parser 和 extractor 对以下 BPMN 特性的支持：

- inclusive gateway；
- event-based gateway；
- loop task 和 multi-instance task；
- 嵌套 subprocess 语义；
- interrupting 和 non-interrupting boundary event；
- timer、error、signal、conditional event 对应的 Claims；
- 在需要时检查 data-flow preservation。

这些扩展应放在核心集成测试和负例测试完成之后，因为每个新 BPMN 特性都需要
回归测试保护。

## 建议开发顺序

1. 为当前通过的样例增加集成测试。
2. 增加一个错误 mCRL2 负例，并断言检查器能够捕获。
3. 实现 Action Preservation Claims。
4. 实现 Message Synchronization Claims。
5. 实现 Exclusive Branch Reachability Claims。
6. 清理并明确中间产物生命周期。
7. 增加 mCRL2 action alphabet 解析。
8. 扩展 parallel gateway 相关 Claims。
9. 继续扩大 BPMN 特性覆盖范围。

