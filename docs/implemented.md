# 当前已实现内容

## 项目定位

ModelInquisitor 是一个用于 BPMN 到 mCRL2 转译流程的旁路验证模块。
它不替代主验证器，也不试图证明 BPMN 模型与生成的 mCRL2 模型在完整语义上绝对等价。

本项目采用更工程化的方式：从 BPMN 源模型中抽取关键语义事实，表示为 Claims，
再将这些 Claims 转换为 modal mu-calculus 公式，并使用 mCRL2 工具链在转译后的
mCRL2 模型上进行验证。

当前验证流程如下：

```text
BPMN XML -> BPMN 解析器 -> Claim 提取器 -> MCF 公式生成器
                                      mCRL2 模型 -> mCRL2 工具链 -> 验证结果
```

## 已实现模块

### 核心模型

核心模型位于 `ModelInquisitor/core/models.py`。

目前定义了：

- `BPMNModel`：完整的 BPMN 协作模型。
- `ProcessModel`：单个 BPMN 流程，包含节点、顺序流和开始事件。
- `BPMNNode`：任务、事件、网关、子流程等 BPMN 节点及其元数据。
- `SequenceFlow`：单个流程内部的控制流边。
- `MessageFlow`：跨参与者的通信边。
- `Participant`：BPMN 协作图中的参与者元数据。
- `Claim`：需要在 mCRL2 端验证的语义断言。

图算法辅助模块位于 `ModelInquisitor/core/graph.py`。

目前提供：

- 从指定节点出发的可达性分析；
- 分支结构的汇合点查找；
- 用于因果关系提取的支配节点分析。

### BPMN 解析器

BPMN 解析器位于 `ModelInquisitor/parsers/bpmn.py`。

当前支持解析：

- BPMN `process`；
- 常见任务节点，包括 `serviceTask`、`receiveTask`、`sendTask`、`userTask`、
  `task`、`scriptTask`；
- `startEvent`、`endEvent`、`parallelGateway`、`exclusiveGateway`、
  `subProcess`、`boundaryEvent`、`intermediateCatchEvent`、
  `intermediateThrowEvent`；
- `sequenceFlow`；
- `participant`；
- `messageFlow`；
- message、timer、conditional、signal、error 等事件定义元数据。

解析器还会记录节点所属流程，并支持将单个流程导出为 NetworkX 有向图，
方便后续进行图分析。

### Claim 提取器

Claim 提取由 `ModelInquisitor/extractors/__init__.py` 统一组织。

目前已经实现五类 Claim。

#### 死锁自由近似检查

实现位于 `ModelInquisitor/extractors/deadlock.py`。

该提取器会为每个 BPMN 流程生成一个 Claim，要求该流程应当能够到达某个end event。

需要注意的是，当前语义是有意采用的近似版本：生成的公式检查的是 end event可达性，而不是严格意义上的全路径死锁自由性质。

#### Action Preservation 检查

实现位于 `ModelInquisitor/extractors/action_preservation.py`。

该提取器会为每个 BPMN 可观察节点生成一个 Claim，要求该节点在转译后的 mCRL2模型中仍然可以作为可达 action 被观察到。

当前覆盖范围包括：

- 普通任务节点；
- send/receive/message 相关任务；
- end event；
- boundary event；
- intermediate catch/throw event；
- 带事件定义的 start event。

生成的公式形如：

```text
<true*>(<exists oid: OrderId. action(oid)>true)
```

这类 Claim 主要用于检查转译完整性：如果 BPMN 中的关键业务动作在 mCRL2 中消失、命名错误或不可达，验证会失败。

#### Message Synchronization 检查

实现位于 `ModelInquisitor/extractors/message_synchronization.py`。

该提取器会为每条 BPMN `messageFlow` 生成一个 Claim，要求该消息在 mCRL2模型中表现为同步后的 communicated action，而不是裸露的 send/receive action。

对一条 message flow，命名策略会推导：

- send action：`s_msg`；
- receive action：`r_msg`；
- communicated action：`c_msg`。

生成的公式同时检查：

```text
<true*>(<exists oid: OrderId. c_msg(oid)>true)
[true* . (exists oid: OrderId. s_msg(oid))]false
[true* . (exists oid: OrderId. r_msg(oid))]false
```

这类 Claim 用于发现通信同步规则缺失、`comm` 配置错误，或原始 send/receive动作意外暴露等问题。

#### 因果依赖检查

实现位于 `ModelInquisitor/extractors/causality.py`。

该提取器会对每个流程计算支配节点关系。如果一个可观察源节点支配另一个可观察目标节点，就生成一个 Claim，表示目标节点不能在源节点之前发生。

这可以捕获直线流程或结构化流程区域中的必要前驱关系。

#### 互斥排他检查

实现位于 `ModelInquisitor/extractors/mutex.py`。

对于拥有多条输出分支的 exclusive gateway，该提取器会查找每条分支中的首个可观察动作，并生成两两互斥的 Claims。

生成的性质用于检查同一次执行 trace 中不应同时出现两个排他分支动作。

### 命名策略

命名策略抽象位于 `ModelInquisitor/strategies/base.py`。

当前具体实现为 `ModelInquisitor/strategies/third_party_bpmn2mcrl2.py`，
用于适配仓库中的 `third-party/bpmn2mcrl2` 转译器命名约定。

它负责将 BPMN 概念映射到 mCRL2 action 名称，包括：

- 任务动作；
- end event 动作；
- message flow 对应的 send、receive、communicated actions；
- 第三方转译器使用的 parallel gateway 同步动作。

通过命名策略，检查器可以保持与转译器实现本身解耦。

### MCF 公式生成

公式生成器位于 `ModelInquisitor/generators/mcf.py`。

它会将 Claims 转换为 modal mu-calculus 公式：

- 死锁自由近似：检查 end event 动作是否可达；
- Action Preservation：检查 BPMN 可观察节点对应 action 是否可达；
- Message Synchronization：检查 message flow 是否同步为 communicated action；
- 因果依赖：检查目标动作不能在源动作之前发生；
- 互斥排他：检查两个分支动作的两种先后顺序都不允许出现。

当前公式默认假设 mCRL2 action 带有 `OrderId` 参数，形式为 `action(oid)`。

### 验证 Runner

验证 runner 位于 `ModelInquisitor/runners/verifier.py`。

它负责执行完整的 mCRL2 验证链路：

```text
mcrl22lps -> lps2pbes -> pbes2bool
```

对每个生成的 Claim 公式，runner 会写出 `.mcf` 文件，将其转换为 PBES，再求解 PBES，并报告该 Claim 是否通过。

如果 mCRL2 命令行工具不在 `PATH` 中，runner 会将每个 Claim 标记为
`not_run`。

### 命令行接口

命令行入口位于 `main.py`。

基本使用方式：

```text
python main.py <source.bpmn> <translated.mcrl2>
```

可选参数：

- `--work-dir`：指定生成 `.lps`、`.mcf`、`.pbes` 等中间产物的目录；
- `--show-formulas`：打印生成的 MCF 公式。

CLI 会输出：

- 紧凑的验证结果表；
- 按 Claim 类型分组的解释；
- 失败详情，或在指定 `--show-formulas` 时输出公式详情。

退出码含义：

- `0`：所有 Claims 均通过；
- `1`：至少一个 Claim 验证为 false；
- `2`：输入文件不存在；
- `3`：模型转换、公式生成、求解失败，或工具链未运行。

## 已实现测试

测试位于 `tests/test_model_inquisitor.py`。

当前覆盖：

- 与第三方转译器兼容的名称清洗规则；
- BPMN parser 是否保留流程、节点、边和 message flow 元数据；
- 流程图边是否正确导出；
- message flow 的源流程和目标流程解析；
- 第三方命名策略是否能匹配样例 mCRL2 中的 action；
- Claim 抽取；
- MCF 公式生成。
- 真实 mCRL2 工具链端到端验证；如果工具链缺失，该测试会自动跳过。

当前本地测试结果：

```text
6 passed
```

## 当前端到端状态

在 `.venv` 依赖安装完成，且 mCRL2 命令行工具已经加入 `PATH` 后，当前样例可以
端到端运行：

```text
.venv/bin/python main.py tests/input/spec.bpmn tests/input/spec.mcrl2 --work-dir .verify-artifacts
```

观测结果：

```text
19 个 Claims 全部通过
```

通过的 Claims 包括：

- 2 个死锁自由近似 Claims；
- 8 个 Action Preservation Claims；
- 3 个 Message Synchronization Claims；
- 6 个因果依赖 Claims。

当前样例没有生成 mutex Claim，因为输入 BPMN 中没有符合当前提取器模式的
exclusive gateway 分支结构。
