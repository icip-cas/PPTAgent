# Product 产品

# Building effective agents 建⽴有效的代理

#### 2024年12⽉20⽇

Over the past year, we've worked with dozens of teams building large language model (LLM) agents across industries. Consistently, the most successful implementations weren't using complex frameworks or specialized libraries. Instead, they were building with simple, composable patterns. 在过去的⼀年⾥,我们与数⼗个团队合作,构建了跨⾏业的⼤型语⾔模型 ( LLM ) 代 理。始终如⼀,最成功的实现并不使⽤复杂的框架或专门的库。相反,他们使⽤简单、

可组合的模式进⾏构建。 In this post, we share what we've learned from working with our customers and building agents ourselves, and give practical advice for developers on building

effective agents. 在这篇⽂章中,我们分享了我们从与客户和建筑代理合作中学到的知识,并为开发商提

供构建有效代理的实⽤建议。

### What are agents? 什么是代理?

"Agent" can be defined in several ways. Some customers define agents as fully autonomous systems that operate independently over extended periods, using various tools to accomplish complex tasks. Others use the term to describe more prescriptive implementations that follow predefined workflows. At Anthropic, we categorize all these variations as agentic systems, but draw an important architectural distinction between workflows and agents:

"代理"可以通过多种⽅式定义。⼀些客户将代理定义为完全⾃主的系统,可以长时间独 ⽴运⾏,使⽤各种⼯具完成复杂的任务。其他⼈使⽤该术语来描述遵循预定义⼯作流程 的更具规范性的实现。在 Anthropic,我们将所有这些变体归类为代理系统,但在⼯作 流和代理之间划出了重要的架构区别:

- Workflows are systems where LLMs and tools are orchestrated through predefined code paths.
- ⼯作流程是通过预定义的代码路径编排LLMs和⼯具的系统。
- Agents, on the other hand, are systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks.

另⼀⽅⾯,代理是LLMs动态指导⾃⼰的流程和⼯具使⽤的系统,保持对其完成任务 ⽅式的控制。

Below, we will explore both types of agentic systems in detail. In Appendix 1 ("Agents in Practice"), we describe two domains where customers have found particular value in using these kinds of systems.

下⾯,我们将详细探讨这两种类型的代理系统。在附录 1("实践中的代理")中,我们描 述了客户发现使⽤此类系统具有特殊价值的两个领域。

## When (and when not) to use agents 何时(以及何时不)使⽤代理

When building applications with LLMs, we recommend finding the simplest solution possible, and only increasing complexity when needed. This might mean not building agentic systems at all. Agentic systems often trade latency and cost for better task performance, and you should consider when this tradeoff makes sense.

当使⽤LLMs构建应⽤程序时,我们建议寻找尽可能最简单的解决⽅案,并且仅在需要 时增加复杂性。这可能意味着根本不构建代理系统。代理系统通常会以延迟和成本来换 取更好的任务性能,您应该考虑这种权衡何时有意义。

When more complexity is warranted, workflows offer predictability and consistency for well-defined tasks, whereas agents are the better option when flexibility and model-driven decision-making are needed at scale. For many applications, however, optimizing single LLM calls with retrieval and in-context examples is usually enough.

当需要更⾼的复杂性时,⼯作流为明确定义的任务提供可预测性和⼀致性,⽽当⼤规模 需要灵活性和模型驱动的决策时,代理是更好的选择。然⽽,对于许多应⽤程序来说, 通过检索和上下⽂⽰例来优化单个LLM调⽤通常就⾜够了。

### When and how to use frameworks 何时以及如何使⽤框架

There are many frameworks that make agentic systems easier to implement, including:

有许多框架可以使代理系统更容易实现,包括:

- LangGraph from LangChain;
- 来⾃LangChain的LangGraph ;
- Amazon Bedrock's AI Agent framework;
- Amazon Bedrock 的AI 代理框架;
- Rivet, a drag and drop GUI LLM workflow builder; and
- Rivet ,⼀个拖放式 GUI LLM⼯作流程构建器;和
- Vellum, another GUI tool for building and testing complex workflows. Vellum ,另⼀个⽤于构建和测试复杂⼯作流程的 GUI ⼯具。

These frameworks make it easy to get started by simplifying standard low-level tasks like calling LLMs, defining and parsing tools, and chaining calls together. However, they often create extra layers of abstraction that can obscure the underlying prompts and responses, making them harder to debug. They can also make it tempting to add complexity when a simpler setup would suffice.

这些框架通过简化标准低级任务(例如调⽤LLMs 、定义和解析⼯具以及将调⽤链接在 ⼀起)使⼊门变得容易。然⽽,它们经常创建额外的抽象层,这些抽象层可能会掩盖底 层的提⽰和响应,从⽽使它们更难以调试。当更简单的设置就⾜够时,它们还可能会增 加复杂性。

We suggest that developers start by using LLM APIs directly: many patterns can be implemented in a few lines of code. If you do use a framework, ensure you understand the underlying code. Incorrect assumptions about what's under the hood are a common source of customer error.

我们建议开发⼈员从直接使⽤LLM API 开始:只需⼏⾏代码即可实现许多模式。如果您 确实使⽤框架,请确保您了解底层代码。对底层内容的错误假设是客户错误的常见来 源。

#### See our cookbook for some sample implementations.

### Building blocks, workflows, and agents 构建块、⼯作流程和代理

In this section, we'll explore the common patterns for agentic systems we've seen in production. We'll start with our foundational building block—the augmented LLM—and progressively increase complexity, from simple compositional workflows to autonomous agents.

在本节中,我们将探讨我们在⽣产中看到的代理系统的常见模式。我们将从我们的基础 构建块——增强的LLM ——开始,并逐步增加复杂性,从简单的组合⼯作流程到⾃主代 理。

#### Building block: The augmented LLM 构建模块:增强LLM

The basic building block of agentic systems is an LLM enhanced with augmentations such as retrieval, tools, and memory. Our current models can actively use these capabilities—generating their own search queries, selecting appropriate tools, and determining what information to retain. 代理系统的基本构建模块是通过检索、⼯具和记忆等增强功能增强的LLM 。我们当前的 模型可以积极使⽤这些功能——⽣成⾃⼰的搜索查询、选择适当的⼯具以及确定要保留 哪些信息。

![](_page_0_Figure_45.jpeg)

The augmented LLM 增强型LLM

- We recommend focusing on two key aspects of the implementation: tailoring these capabilities to your specific use case and ensuring they provide an easy, welldocumented interface for your LLM. While there are many ways to implement these augmentations, one approach is through our recently released Model
Context Protocol, which allows developers to integrate with a growing ecosystem of third-party tools with a simple client implementation. 我们建议重点关注实施的两个关键⽅⾯:根据您的特定⽤例定制这些功能,并确保它们

为您的LLM提供简单且记录良好的界⾯。虽然实现这些增强的⽅法有很多,但⼀种⽅法 是通过我们最近发布的模型上下⽂协议,它允许开发⼈员通过简单的客户端实现与不断 增长的第三⽅⼯具⽣态系统集成。

For the remainder of this post, we'll assume each LLM call has access to these augmented capabilities.

对于本⽂的其余部分,我们将假设每个LLM调⽤都可以访问这些增强功能。

#### Workflow: Prompt chaining ⼯作流程:提示链接

Prompt chaining decomposes a task into a sequence of steps, where each LLM call processes the output of the previous one. You can add programmatic checks (see "gate" in the diagram below) on any intermediate steps to ensure that the process is still on track.

提⽰链接将任务分解为⼀系列步骤,其中每个LLM调⽤都会处理前⼀个步骤的输出。您 可以在任何中间步骤上添加编程检查(请参见下图中的"门"),以确保流程仍按计划进 ⾏。

![](_page_0_Figure_55.jpeg)

The prompt chaining workflow 提示链接⼯作流程

When to use this workflow: This workflow is ideal for situations where the task can be easily and cleanly decomposed into fixed subtasks. The main goal is to trade off latency for higher accuracy, by making each LLM call an easier task.

何时使⽤此⼯作流程:此⼯作流程⾮常适合任务可以轻松、⼲净地分解为固定⼦任务的 情况。主要⽬标是通过使每个LLM调⽤变得更容易,来权衡延迟以获得更⾼的准确性。

提⽰链有⽤的⽰例:

- Generating Marketing copy, then translating it into a different language. ⽣成营销⽂案,然后将其翻译成其他语⾔。
- Writing an outline of a document, checking that the outline meets certain criteria, then writing the document based on the outline.
- 编写⽂档⼤纲,检查⼤纲是否符合某些标准,然后根据⼤纲编写⽂档。

### Workflow: Routing ⼯作流程:路由

Examples where prompt chaining is useful:

Routing classifies an input and directs it to a specialized followup task. This workflow allows for separation of concerns, and building more specialized prompts. Without this workflow, optimizing for one kind of input can hurt performance on other inputs.

路由对输⼊进⾏分类,并将其引导⾄专门的后续任务。此⼯作流程允许分离关注点并构 建更专业的提⽰。如果没有此⼯作流程,针对⼀种输⼊的优化可能会损害其他输⼊的性 能。

|  |  | LLM Call 1 |  |
| --- | --- | --- | --- |
| ln | LLM Call Router | LLM Call 2 | Out |
|  |  | LLM Call 3 | 门 |

The routing workflow 路由⼯作流程

When to use this workflow: Routing works well for complex tasks where there are distinct categories that are better handled separately, and where classification can be handled accurately, either by an LLM or a more traditional classification model/algorithm.

何时使⽤此⼯作流程:路由⾮常适合复杂的任务,其中存在更好单独处理的不同类别, 并且可以通过LLM或更传统的分类模型/算法准确处理分类。

#### Examples where routing is useful:

路由有⽤的⽰例:

- Directing different types of customer service queries (general questions, refund requests, technical support) into different downstream processes, prompts, and tools.
- 将不同类型的客户服务查询(⼀般问题、退款请求、技术⽀持)引导到不同的下游 流程、提⽰和⼯具中。
- Routing easy/common questions to smaller models like Claude 3.5 Haiku and hard/unusual questions to more capable models like Claude 3.5 Sonnet to optimize cost and speed.
- 将简单/常见问题路由到较⼩的模型(如 Claude 3.5 Haiku),将困难/不寻常的问 题路由到更强⼤的模型(如 Claude 3.5 Sonnet),以优化成本和速度。

#### Workflow: Parallelization

⼯作流程:并⾏化

LLMs can sometimes work simultaneously on a task and have their outputs aggregated programmatically. This workflow, parallelization, manifests in two key variations:

LLMs有时可以同时完成⼀项任务,并以编程⽅式汇总其输出。此⼯作流程(并⾏化) 体现在两个关键变体中:

- Sectioning: Breaking a task into independent subtasks run in parallel.
- 分段:将任务分解为并⾏运⾏的独⽴⼦任务。
- Voting: Running the same task multiple times to get diverse outputs. 投票:多次运⾏同⼀任务以获得不同的输出。

|  | 1 | LLM Call 1 | 7 |  |  |
| --- | --- | --- | --- | --- | --- |
| In | > | LLM Call 2 | > | Aggregator | > Out |
|  |  | LLM Call 3 | Σ |  |  |

#### The parallelization workflow

并⾏化⼯作流程

When to use this workflow: Parallelization is effective when the divided subtasks can be parallelized for speed, or when multiple perspectives or attempts are needed for higher confidence results. For complex tasks with multiple considerations, LLMs generally perform better when each consideration is

handled by a separate LLM call, allowing focused attention on each specific aspect.

#### Examples where parallelization is useful:

- Sectioning:
	- Implementing guardrails where one model instance processes user
	- queries while another screens them for inappropriate content or requests. This tends to perform better than having the same LLM call handle both guardrails and the core response.
	- Automating evals for evaluating LLM performance, where each LLM call evaluates a different aspect of the model's performance on a given prompt.
- Voting:

The orchestrator-workers workflow

- Reviewing a piece of code for vulnerabilities, where several different prompts review and flag the code if they find a problem.
	- Evaluating whether a given piece of content is inappropriate, with
	- multiple prompts evaluating different aspects or requiring different vote thresholds to balance false positives and negatives.

#### Workflow: Orchestrator-workers

In the orchestrator-workers workflow, a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results.

在orchestrator-workers⼯作流程中,中央LLM动态分解任务,将它们委托给worker LLMs ,并综合其结果。

|  |  |  | ----> | LLM Call 1 |  |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- |
| In | > | Orchestrator | ········· | LLM Call 2 | ········· | Synthesizer | > Out |
|  |  |  |  | LLM Call 3 | កា |  |  |

you can't predict the subtasks needed (in coding, for example, the number of files that need to be changed and the nature of the change in each file likely depend on the task). Whereas it's topographically similar, the key difference from parallelization is its flexibility—subtasks aren't pre-defined, but determined by the orchestrator based on the specific input.

何时使⽤此⼯作流程:此⼯作流程⾮常适合您⽆法预测所需⼦任务的复杂任务(例如, 在编码中,需要更改的⽂件数量以及每个⽂件中可能发⽣的更改的性质)取决于任 务)。虽然它在拓扑上相似,但与并⾏化的主要区别在于它的灵活性——⼦任务不是预 先定义的,⽽是由协调器根据特定输⼊确定。

Example where orchestrator-workers is useful:

- Orchestrator-Workers 有⽤的⽰例:
	- Coding products that make complex changes to multiple files each time. Search tasks that involve gathering and analyzing information from multiple sources for possible relevant information.

Workflow: Evaluator-optimizer

⼯作流程:评估器-优化器

In the evaluator-optimizer workflow, one LLM call generates a response while another provides evaluation and feedback in a loop.

在评估器-优化器⼯作流程中,⼀个LLM调⽤⽣成响应,⽽另⼀个调⽤则在循环中提供评 估和反馈。

![](_page_0_Figure_111.jpeg)

The evaluator-optimizer workflow

评估器-优化器⼯作流程

When to use this workflow: This workflow is particularly effective when we have clear evaluation criteria, and when iterative refinement provides measurable value. The two signs of good fit are, first, that LLM responses can be demonstrably improved when a human articulates their feedback; and second, that the LLM can provide such feedback. This is analogous to the iterative writing process a human writer might go through when producing a polished document.

何时使⽤此⼯作流程:当我们有明确的评估标准并且迭代细化提供可衡量的价值时,此 ⼯作流程特别有效。良好契合的两个标志是,⾸先,当⼈们清楚地表达他们的反馈时, LLM反应可以得到明显改善;其次, LLM可以提供此类反馈。这类似于⼈类作家在制作 精美⽂档时可能经历的迭代写作过程。

Examples where evaluator-optimizer is useful:

- 评估器优化器有⽤的⽰例:
	- Literary translation where there are nuances that the translator LLM might not capture initially, but where an evaluator LLM can provide useful critiques. ⽂学翻译中存在译者LLM最初可能⽆法捕捉到的细微差别,但评估者LLM可以提供 有⽤的批评。
	- Complex search tasks that require multiple rounds of searching and analysis to gather comprehensive information, where the evaluator decides whether further searches are warranted.
		- 复杂的搜索任务,需要多轮搜索和分析来收集全⾯的信息,评估者决定是否需要进 ⼀步搜索。

Agents 代理商

Agents are emerging in production as LLMs mature in key capabilities understanding complex inputs, engaging in reasoning and planning, using tools reliably, and recovering from errors. Agents begin their work with either a command from, or interactive discussion with, the human user. Once the task is clear, agents plan and operate independently, potentially returning to the human for further information or judgement. During execution, it's crucial for the agents to gain "ground truth" from the environment at each step (such as tool call results or code execution) to assess its progress. Agents can then pause for human feedback at checkpoints or when encountering blockers. The task often terminates upon completion, but it's also common to include stopping conditions (such as a maximum number of iterations) to maintain control.

随着LLMs在关键能⼒⽅⾯的成熟——理解复杂的输⼊、参与推理和规划、可靠地使⽤ ⼯具以及从错误中恢复,代理正在⽣产中出现。代理通过⼈类⽤户的命令或与⼈类⽤户 的交互式讨论开始⼯作。⼀旦任务明确,智能体就会独⽴计划和操作,并有可能返回⼈ 类以获取进⼀步的信息或判断。在执⾏过程中,代理在每个步骤(例如⼯具调⽤结果或 代码执⾏)中从环境中获取"基本事实"以评估其进度⾄关重要。然后,特⼯可以在检查 站或遇到拦截者时暂停以获取⼈⼯反馈。任务通常在完成后终⽌,但通常还包含停⽌条 件(例如最⼤迭代次数)以保持控制。

Agents can handle sophisticated tasks, but their implementation is often straightforward. They are typically just LLMs using tools based on environmental feedback in a loop. It is therefore crucial to design toolsets and their documentation clearly and thoughtfully. We expand on best practices for tool development in Appendix 2 ("Prompt Engineering your Tools"). 代理可以处理复杂的任务,但它们的实现通常很简单。他们通常只是LLMs使⽤基于循

环环境反馈的⼯具。因此,清晰且深思熟虑地设计⼯具集及其⽂档⾄关重要。我们在附 录 2("提⽰设计您的⼯具")中详细介绍了⼯具开发的最佳实践。

![](_page_0_Figure_125.jpeg)

Autonomous agent ⾃主代理

When to use agents: Agents can be used for open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path. The LLM will potentially operate for many turns, and you

must have some level of trust in its decision-making. Agents' autonomy makes

must have some level of trust in its decision-making. Agents' autonomy makes them ideal for scaling tasks in trusted environments.

何时使⽤代理:代理可⽤于解决难以或不可能预测所需步骤数以及⽆法硬编码固定路径 的开放式问题。 LLM可能会运作很多轮,你必须对其决策有⼀定程度的信任。代理的⾃ 主性使它们成为在可信环境中扩展任务的理想选择。

The autonomous nature of agents means higher costs, and the potential for compounding errors. We recommend extensive testing in sandboxed environments, along with the appropriate guardrails.

代理的⾃主性意味着更⾼的成本,并且可能会出现复合错误。我们建议在沙盒环境中进 ⾏⼴泛的测试,并配备适当的护栏。

#### Examples where agents are useful:

代理有⽤的⽰例:

The following examples are from our own implementations:

以下⽰例来⾃我们⾃⼰的实现:

- A coding Agent to resolve SWE-bench tasks, which involve edits to many files based on a task description;
	- ⽤于解决SWE-bench 任务的编码代理,其中涉及根据任务描述对许多⽂件进⾏编 辑;
- Our "computer use" reference implementation, where Claude uses a computer to accomplish tasks.

| 我们的"计算机使⽤"参考实现,克劳德使⽤计算机来完成任务。 |
| --- |

| Human | Interface |  | LLM |  | Environment |
| --- | --- | --- | --- | --- | --- |
| Query | > |  |  |  |  |
| Until tasks clear |  |  |  |  |  |
|  | Clarify |  |  |  |  |
|  | Refine |  |  |  |  |
|  |  | Send context |  |  |  |
|  |  |  | > | Search files |  |
|  |  |  |  |  | > |
|  |  |  |  | Return paths |  |
|  |  |  |  | Until tests pass |  |
|  |  |  |  | Write code |  |
|  |  |  |  | Status |  |
|  |  |  |  | Test |  |
|  |  |  |  | Results |  |
|  |  | Complete |  |  |  |
| Display |  |  |  |  |  |

High-level flow of a coding agent 编码代理的⾼级流程

### Combining and customizing these patterns 组合和定制这些模式

These building blocks aren't prescriptive. They're common patterns that developers can shape and combine to fit different use cases. The key to success, as with any LLM features, is measuring performance and iterating on implementations. To repeat: you should consider adding complexity *only* when it demonstrably improves outcomes.

这些构建块不是规定性的。它们是开发⼈员可以塑造和组合以适应不同⽤例的常见模 式。与任何LLM功能⼀样,成功的关键是衡量性能和迭代实施。重复⼀遍:只有当复杂 性明显改善结果时,您才应该考虑增加复杂性。

### Summary 概括

Success in the LLM space isn't about building the most sophisticated system. It's about building the *right* system for your needs. Start with simple prompts, optimize them with comprehensive evaluation, and add multi-step agentic systems only when simpler solutions fall short.

LLM领域的成功并不在于构建最复杂的系统。这是为了构建适合您需求的系统。从简单 的提⽰开始,通过综合评估对其进⾏优化,仅在简单的解决⽅案⽆法满⾜要求时才添加 多步骤代理系统。

When implementing agents, we try to follow three core principles: 在实施代理时,我们尝试遵循三个核⼼原则:

- 1. Maintain simplicity in your agent's design.
保持代理设计的简单性。

- 2. Prioritize transparency by explicitly showing the agent's planning steps.
通过明确显⽰代理的规划步骤来优先考虑透明度。

- 3. Carefully craft your agent-computer interface (ACI) through thorough tool documentation and testing.
通过彻底的⼯具⽂档和测试精⼼设计您的代理计算机接⼜ (ACI)。

Frameworks can help you get started quickly, but don't hesitate to reduce abstraction layers and build with basic components as you move to production. By following these principles, you can create agents that are not only powerful but also reliable, maintainable, and trusted by their users.

框架可以帮助您快速⼊门,但在转向⽣产时请毫不犹豫地减少抽象层并使⽤基本组件进 ⾏构建。通过遵循这些原则,您可以创建不仅功能强⼤⽽且可靠、可维护且受到⽤户信 任的代理。

#### Acknowledgements 致谢

Written by Erik Schluntz and Barry Zhang. This work draws upon our experiences building agents at Anthropic and the valuable insights shared by our customers, for which we're deeply grateful.

由埃⾥克·施伦茨和巴⾥·张撰写。这项⼯作借鉴了我们在 Anthropic 建⽴代理的经验以 及我们的客户分享的宝贵见解,对此我们深表感谢。

### Appendix 1: Agents in practice 附录1:代理实践

Our work with customers has revealed two particularly promising applications for AI agents that demonstrate the practical value of the patterns discussed above. Both applications illustrate how agents add the most value for tasks that require both conversation and action, have clear success criteria, enable feedback loops, and integrate meaningful human oversight.

我们与客户的合作揭⽰了⼈⼯智能代理的两个特别有前途的应⽤,它们证明了上述模式 的实际价值。这两个应⽤程序都说明了代理如何为需要对话和⾏动的任务增加最⼤价 值,具有明确的成功标准,启⽤反馈循环,并集成有意义的⼈⼯监督。

#### A. Customer support A、客户⽀持

Customer support combines familiar chatbot interfaces with enhanced capabilities through tool integration. This is a natural fit for more open-ended agents because: 客户⽀持通过⼯具集成将熟悉的聊天机器⼈界⾯与增强的功能结合起来。这对于更多开

放式代理来说是⾃然的选择,因为:

- Support interactions naturally follow a conversation flow while requiring access to external information and actions;
⽀持交互⾃然地遵循对话流程,同时需要访问外部信息和操作;

- Tools can be integrated to pull customer data, order history, and knowledge base articles;
可以集成⼯具来提取客户数据、订单历史记录和知识库⽂章;

- Actions such as issuing refunds or updating tickets can be handled programmatically; and
退款或更新机票等操作可以通过编程⽅式处理;和

- Success can be clearly measured through user-defined resolutions. 成功可以通过⽤户定义的解决⽅案来明确衡量。
Several companies have demonstrated the viability of this approach through usage-based pricing models that charge only for successful resolutions, showing

confidence in their agents' effectiveness.

⼀些公司已经通过基于使⽤的定价模型证明了这种⽅法的可⾏性,该模型仅对成功的解 决⽅案收费,这表明了对其代理效率的信⼼。

#### B. Coding agents B. 编码剂

The software development space has shown remarkable potential for LLM features, with capabilities evolving from code completion to autonomous problemsolving. Agents are particularly effective because:

软件开发领域已显⽰出LLM功能的巨⼤潜⼒,其功能从代码完成发展到⾃主解决问题。 代理特别有效,因为:

- Code solutions are verifiable through automated tests; 代码解决⽅案可通过⾃动化测试进⾏验证;
- Agents can iterate on solutions using test results as feedback; 代理可以使⽤测试结果作为反馈来迭代解决⽅案;
- The problem space is well-defined and structured; and 问题空间定义明确且结构合理;和
- Output quality can be measured objectively. 输出质量可以客观地衡量。

In our own implementation, agents can now solve real GitHub issues in the SWEbench Verified benchmark based on the pull request description alone. However, whereas automated testing helps verify functionality, human review remains crucial for ensuring solutions align with broader system requirements.

在我们⾃⼰的实现中,代理现在可以仅根据拉取请求描述来解决SWE-bench Verified基 准中的实际 GitHub 问题。然⽽,虽然⾃动化测试有助于验证功能,但⼈⼯审查对于确 保解决⽅案符合更⼴泛的系统要求仍然⾄关重要。

# Appendix 2: Prompt engineering your tools

附录 2:快速设计您的⼯具

No matter which agentic system you're building, tools will likely be an important part of your agent. Tools enable Claude to interact with external services and APIs by specifying their exact structure and definition in our API. When Claude responds, it will include a tool use block in the API response if it plans to invoke a tool. Tool definitions and specifications should be given just as much prompt engineering attention as your overall prompts. In this brief appendix, we describe how to prompt engineer your tools.

⽆论您正在构建哪种代理系统,⼯具都可能是代理的重要组成部分。⼯具使 Claude 能 够通过在我们的 API 中指定外部服务和 API 的确切结构和定义来与外部服务和 API 进⾏ 交互。当 Claude 响应时,如果它计划调⽤⼯具,它将在 API 响应中包含⼀个⼯具使⽤ 块。⼯具定义和规范应该像整体提⽰⼀样得到及时的⼯程关注。在这个简短的附录中, 我们描述了如何提⽰设计您的⼯具。

There are often several ways to specify the same action. For instance, you can specify a file edit by writing a diff, or by rewriting the entire file. For structured output, you can return code inside markdown or inside JSON. In software engineering, differences like these are cosmetic and can be converted losslessly from one to the other. However, some formats are much more difficult for an LLM to write than others. Writing a diff requires knowing how many lines are changing in the chunk header before the new code is written. Writing code inside JSON (compared to markdown) requires extra escaping of newlines and quotes.

通常有多种⽅法来指定相同的操作。例如,您可以通过写⼊差异或重写整个⽂件来指定 ⽂件编辑。对于结构化输出,您可以在 markdown 或 JSON 中返回代码。在软件⼯程 中,此类差异是表⾯性的,可以⽆损地从⼀种差异转换为另⼀种差异。然⽽,对于LLM 来说,某些格式⽐其他格式更难编写。编写差异需要知道在编写新代码之前块头中有多 少⾏发⽣了变化。在 JSON 中编写代码(与 Markdown 相⽐)需要额外转义换⾏符和 引号。

Our suggestions for deciding on tool formats are the following:

我们对决定⼯具格式的建议如下:

- Give the model enough tokens to "think" before it writes itself into a corner. 在模型陷⼊困境之前,给模型⾜够的令牌来"思考" 。
- Keep the format close to what the model has seen naturally occurring in text on the internet.

- 保持格式接近模型在互联⽹上⾃然出现的⽂本格式。
- Make sure there's no formatting "overhead" such as having to keep an accurate count of thousands of lines of code, or string-escaping any code it writes. 确保没有格式化"开销" ,例如必须准确计数数千⾏代码,或者对其编写的任何代码 进⾏字符串转义。

One rule of thumb is to think about how much effort goes into human-computer interfaces (HCI), and plan to invest just as much effort in creating good *agent*computer interfaces (ACI). Here are some thoughts on how to do so:

⼀条经验法则是考虑在⼈机界⾯ (HCI) 上投⼊多少精⼒,并计划投⼊同样多的精⼒来创 建良好的代理计算机界⾯ (ACI)。以下是关于如何执⾏此操作的⼀些想法:

- Put yourself in the model's shoes. Is it obvious how to use this tool, based on the description and parameters, or would you need to think carefully about it? If so, then it's probably also true for the model. A good tool definition often includes example usage, edge cases, input format requirements, and clear boundaries from other tools.
设⾝处地为模特着想。根据描述和参数,如何使⽤这个⼯具是否显⽽易见,或者您 是否需要仔细考虑?如果是这样,那么模型可能也是如此。好的⼯具定义通常包括 ⽰例⽤法、边缘情况、输⼊格式要求以及与其他⼯具的明确界限。

- How can you change parameter names or descriptions to make things more obvious? Think of this as writing a great docstring for a junior developer on your team. This is especially important when using many similar tools.
如何更改参数名称或描述以使事情更加明显?将此视为为团队中的初级开发⼈员编 写出⾊的⽂档字符串。当使⽤许多类似的⼯具时,这⼀点尤其重要。

- Test how the model uses your tools: Run many example inputs in our workbench to see what mistakes the model makes, and iterate. 测试模型如何使⽤您的⼯具:在我们的⼯作台中运⾏许多⽰例输⼊,以查看模型犯 了哪些错误,然后进⾏迭代。
- Poka-yoke your tools. Change the arguments so that it is harder to make mistakes.

防错你的⼯具。改变论点,这样就更难犯错误。

While building our agent for SWE-bench, we actually spent more time optimizing our tools than the overall prompt. For example, we found that the model would make mistakes with tools using relative filepaths after the agent had moved out of the root directory. To fix this, we changed the tool to always require absolute filepaths—and we found that the model used this method flawlessly.

在为SWE-bench构建代理时,我们实际上花费了⽐整体提⽰更多的时间来优化我们的⼯ 具。例如,我们发现在代理移出根⽬录后,模型会使⽤相对⽂件路径的⼯具出错。为了 解决这个问题,我们将⼯具更改为始终需要绝对⽂件路径,并且我们发现该模型完美地 使⽤了这种⽅法。

| Claude | Press Inquiries | Terms of Service – | © 2024 Anthropic |
| --- | --- | --- | --- |
|  |  | Consumer | PBC |
| API | Support |  |  |
|  |  | Terms of Service – |  |
| Team | Status | Commercial |  |
| Pricing | Availability | Privacy Policy |  |
| Research | Twitter | Usage Policy |  |
| Company | LinkedIn | Responsible |  |
| Customers | YouTube | Disclosure Policy |  |
| News |  | Compliance |  |
|  |  | Privacy Choices |  |
| Careers |  |  |  |
