# AI Glossary for Newbies – From Fundamentals to OpenKubes

> This glossary is for beginners, and especially for newbies. Technical terms stay in English (with a short explanation), because that's exactly how you'll hear them on the job. Every entry: **What it is** · **Analogy** · **Mini-example** · **Why it matters / pitfall**.

## Who is this for and how do you read it?

This glossary explains the terms that actually come up in real projects: in meetings, in pull-request descriptions, and in the Slack messages when something breaks at 2am. The structure deliberately goes from concrete to abstract, in four stages:

1. **Fundamentals** – what the model itself works with
2. **Knowledge from outside** – how the model gets current and company-specific knowledge
3. **Taking action** – how the model does something instead of just talking
4. **Quality & operations** – how you know it works, and how to run it safely and affordably

To **look something up**, jump straight to the term. To **learn**, read one stage end to end – the terms build on each other.

---

## Stage 1 – Fundamentals: What the model itself works with

### Large Language Model (LLM)

**What it is:** The engine. A program trained on enormous amounts of text that learned to predict the next word, over and over, until predicting the next word turned into something that looks like reasoning.

**Analogy:** A very well-read acquaintance who has read almost everything but doesn't remember your specific conversation until you remind them. Every time, they start fresh.

**Mini-example:** Claude, GPT and Gemini are all LLMs.

**Why it matters / pitfall:** The model is not the product. What you build around it (everything else in this glossary) is the product. The LLM alone is just the engine – without a car it doesn't drive.

### Token

**What it is:** Models don't read in words, but in tokens – small chunks of text: sometimes a whole word, sometimes part of one, sometimes a punctuation mark.

**Analogy:** Like syllables when reading aloud – except the boundaries fall in different places than we'd expect.

**Mini-example:** "Engineering" might be one token. "Unbelievably" splits into several.

**Why it matters / pitfall:** You pay per token, and the model's memory is measured in tokens. When something feels expensive or slow, count the tokens first.

### Context Window

**What it is:** The maximum amount of text (measured in tokens) a model can read, remember and reference during a single interaction. Anything outside that window simply does not exist to the model.

**Analogy:** A desk. The context window is the size of the desktop. There can be a whole filing cabinet in the next room – but what isn't on the desk, the model can't see.

**Mini-example:** If you load a 500-page manual into the chat but only the first pages fit in the window, the model can't answer about page 480.

**Why it matters / pitfall:** A bigger desk sounds like the fix for everything – but it isn't. Research on what's called **context rot** shows that models get less reliable the more you cram onto that desk, even when nothing on it is wrong.

### Prompt

**What it is:** The text you give the model. Often there's a **system prompt** (the ground rules that always apply) and a **user prompt** (the concrete request).

**Analogy:** A work instruction to a new colleague. The clearer it is, the better the result.

**Mini-example:** "Summarize this text in three bullet points" is a better prompt than "do something with the text".

**Why it matters / pitfall:** Most quality comes from better prompts, not from a more expensive model.

### Inference

**What it is:** Inference is the moment a fully trained model is actually used – you send a prompt, the model computes the answer. Distinct from training (the one-time, expensive learning done beforehand).

**Analogy:** Training is years of study; inference is the single question you ask the expert afterwards.

**Mini-example:** Every chat message and every API call to a model is one inference.

**Why it matters / pitfall:** In production you almost always pay for inference, not training. Latency and cost per answer arise here – which is why levers like prompt caching (Stage 4) pay off.

### Reasoning

**What it is:** Reasoning means a model breaks a task into intermediate steps instead of answering immediately ("chain-of-thought"). Some models are specifically trained for this – so-called reasoning models – and "think" longer before answering.

**Analogy:** Not doing a math problem in your head, but working it out step by step on paper – the intermediate steps make the result more reliable.

**Mini-example:** On a tricky logic or coding task, a reasoning model often delivers better results because it works through the intermediate steps.

**Why it matters / pitfall:** Reasoning costs more tokens and time (it thinks longer). For simple tasks it's overkill – more thinking isn't always better, just more expensive.

### Temperature

**What it is:** A setting that controls how random the output is. Low (near 0) = focused, predictable, similar answer every time. High = more varied and creative, but also less predictable.

**Analogy:** A dial for randomness. Low = the same song every time, high = surprises.

**Mini-example:** For code generation or data extraction you use low temperature; for brainstorming or ad copy, a higher one.

**Why it matters / pitfall:** High temperature raises the risk of hallucinations and makes results hard to reproduce. Keep it low for reliable pipelines.

### Parameters / Model Size

**What it is:** Parameters are the "tuning knobs" a model learns during training. Their count (e.g. 7B = 7 billion, 70B = 70 billion) is a rough measure of a model's size and capacity.

**Analogy:** Roughly like the number of neurons in a brain – more tends to be more capable, but also "more expensive to maintain".

**Mini-example:** A 7B model runs on a single GPU; a 70B model needs several, or very large, GPUs.

**Why it matters / pitfall:** Bigger isn't automatically better for your task – a smaller, specialized model is often faster, cheaper and good enough. Model size also determines what you can self-host (relevant e.g. for GPU nodes).

### Knowledge Cutoff

**What it is:** The point in time up to which a model's training data reaches. Anything that happened afterwards, the model doesn't know on its own.

**Analogy:** A textbook with a print date – what happens after printing isn't in it.

**Mini-example:** Ask a model about an event from last week and it can only guess – unless you give it the info via RAG or web search.

**Why it matters / pitfall:** The cutoff is the main reason RAG and tool use (web search) exist. Always double-check confident answers about current topics.

### Multimodal

**What it is:** A multimodal model can process or generate not only text but also images, audio and sometimes video – several "modalities" in one model.

**Analogy:** Instead of an employee who can only read, one who can also see and hear.

**Mini-example:** You upload a screenshot and ask "what's misconfigured here?" – the model reads the image.

**Why it matters / pitfall:** Images and audio often cost far more tokens than text. And not every model handles every modality – check what it supports first.

### Hallucination

**What it is:** When the model makes something up and still presents it fluently, confidently and nicely formatted. It isn't lying on purpose – it just computes the most likely next word, and sometimes that's simply wrong.

**Analogy:** A test-taker who doesn't know an answer but writes something convincing anyway, instead of saying "I don't know".

**Mini-example:** The model cites a plausible-sounding law or source that doesn't exist.

**Why it matters / pitfall:** Never take critical output unchecked – especially numbers, quotes, sources and code. Countermeasures include RAG (Stage 2) and evals (Stage 4).

---

## Stage 2 – Knowledge from outside: How the model gets its own knowledge

### Embedding

**What it is:** An embedding turns a piece of text into a list of numbers that captures its meaning – not its exact wording. Texts with similar meaning end up with similar numbers.

**Analogy:** Like coordinates on a map of meaning. What's close in content gets close coordinates.

**Mini-example:** "The dog ran fast" and "the canine sprinted" land close together, even though they share almost no words.

**Why it matters / pitfall:** This makes search smarter than keyword matching – you compare meaning, not spelling.

### Vector Database

**What it is:** The place to store all those embedding number-lists and search through them fast.

**Analogy:** A normal database is a phone book (exact matches). A vector database is a "find me something similar" shelf.

**Mini-example:** Pinecone, Qdrant and pgvector are common names from job postings.

**Why it matters / pitfall:** Which one you pick matters less than beginners assume. Getting the embeddings and search logic right matters more than the product.

### Chunking

**What it is:** Before documents become embeddings, they're split into smaller pieces ("chunks") – e.g. paragraphs. Each chunk is embedded individually.

**Analogy:** Filing a book chapter by chapter, so you later get back exactly the right chapter, not the whole book.

**Mini-example:** A 40-page PDF is split into 120 sections; for a question only the 3 relevant ones come back.

**Why it matters / pitfall:** Chunks that are too big bring noise; too small tear apart the context. Bad chunking is one of the most common causes of bad RAG results.

### RAG (Retrieval-Augmented Generation)

**What it is:** Before answering, you retrieve relevant documents and pass them along as part of the context. The model then answers based on those documents.

**Analogy:** An open-book exam instead of a closed-book one. With RAG you hand the model exactly the right pages before it answers.

**Mini-example:** A support bot that pulls the right manual page from the vector database before answering and quotes from it.

**Why it matters / pitfall:** RAG is a retrieval problem before it's a generation problem. If the wrong document is retrieved, even the best model writes a confident, well-formatted, **wrong** answer. Fix retrieval first, don't blame the model.

### Fine-Tuning

**What it is:** Further-training an existing model on your own examples so it better handles a style, format or task. This changes the model itself – unlike RAG.

**Analogy:** RAG is "bring your notes into the exam". Fine-tuning is "take a specialized course beforehand".

**Mini-example:** Fine-tune a model on thousands of example tickets so it writes in your house style.

**Why it matters / pitfall:** Fine-tuning brings new style but **no** current factual knowledge – that's what RAG is for. Rule of thumb: prompting first, then RAG, fine-tuning last.

---

## Stage 3 – Taking action: When the model does something instead of just talking

### Tool Use / Function Calling

**What it is:** Lets the model do more than generate text. You describe a function it's allowed to call, and the model can decide to call it and use the result.

**Analogy:** You give the model hands. It could already talk; now it can also reach out and act.

**Mini-example:** Instead of "I can't see the order status", the model calls `order_status(id)` and answers with the real result.

**Why it matters / pitfall:** The model **proposes**, your code **disposes**. That's exactly the line between a chatbot (talks about your order) and an agent (goes and checks it).

### Agent & Agentic Loop

**What it is:** An agent is an LLM with tool use that pursues a task on its own. The agentic loop is the cycle it runs by itself: gather context, act, verify, repeat – without a human typing a new instruction at every step.

**Analogy:** An intern given a goal, who works through it step by step, checks along the way, and keeps going until it's right.

**Mini-example:** A coding agent reads a file, changes it, runs the tests, sees an error, fixes it – several rounds with no questions in between.

**Why it matters / pitfall:** What separates a good loop from a runaway one is the **stopping condition**. A loop that can't tell when it's done – or when it's failing – burns through your budget. Always set limits: max steps, max cost, a clear success criterion.

### MCP (Model Context Protocol)

**What it is:** A standard for AI models to connect to external tools and data sources – without every company writing custom glue code for every tool. Introduced by Anthropic in November 2024.

**Analogy:** Like a USB port. You build **one** connector for your tool, and any model that speaks MCP can use it.

**Mini-example:** Before MCP you needed three vendor-specific integrations for calendar, database and ticketing. With MCP: one connector per tool.

**Why it matters / pitfall:** MCP has quickly become close to a standard, which is why it shows up near the top of almost every AI engineering job listing. Relevant for us: e.g. the Rovo MCP for Jira/Confluence – more in the OpenKubes part.

---

## Stage 4 – Quality & operations: How you know it works

### Evals

**What it is:** Automated tests that grade whether your AI system's output is good – the way unit tests grade whether your code works. Without evals, you're guessing.

**Analogy:** A test catalog in a driving exam: not "feels safe", but a measurable checklist.

**Mini-example:** 200 example questions with expected answers; after each change the set runs through and you see whether the pass rate goes up or down.

**Why it matters / pitfall:** Evals turn "feels better" into a number. Teams that skip evals aren't faster – they're flying blind.

### Guardrails

**What it is:** The checks that stop a model from doing something it shouldn't, before the output reaches a user. Three kinds: filter what goes in, filter what comes out, and restrict which tools it can call.

**Analogy:** The difference between a car with brakes and an engine bolted bare onto a frame.

**Mini-example:** A support agent may look up orders but not issue a refund – the tool simply isn't available to it.

**Why it matters / pitfall:** Guardrails aren't optional polish. They're the difference between a demo and something you can put in front of real users.

### Prompt Caching

**What it is:** Stores the part of your prompt that doesn't change (e.g. a long system prompt or a big document), so the model doesn't have to reprocess it on every call.

**Analogy:** Scan a document once and file it, instead of reading it aloud again for every question.

**Mini-example:** Your agent sends the same 5,000 tokens of instructions with every request, only the last 50 change. With caching you pay full price once and a fraction on every repeat.

**Why it matters / pitfall:** For anyone running an agent in production, it's one of the simplest levers against a bill that gets you a Slack message from finance.

### Latency & Throughput

**What it is:** Latency is the time until the answer (how long does a single user wait?). Throughput is how many requests the system handles per unit of time (how many users at once?).

**Analogy:** Latency = how fast a single dish is served. Throughput = how many guests the kitchen serves per hour.

**Mini-example:** A chat needs low latency (feels instant); an overnight batch job needs high throughput and latency doesn't matter.

**Why it matters / pitfall:** The two can be traded against each other (batching raises throughput but often latency). Clarify what counts first – and distinguish "time to first token" from total time.

### Context Engineering

**What it is:** The craft of putting exactly the right thing into the model's context window – not too much, not too little, in the right order. The evolution of "prompt engineering" as systems get more complex.

**Analogy:** Setting the desk for a task: only the papers needed right now, well sorted – and the rest cleared away.

**Mini-example:** Instead of sending the whole chat history, you summarize older parts and attach only the three relevant documents.

**Why it matters / pitfall:** Because context rot is real, more context isn't better – the right context is better.

---

## Key takeaways – what ties it all together

- **The model is not the product.** RAG, tool use, evals and guardrails are what turn a model into something reliable.
- **A bigger context window is not automatically better** (context rot).
- **If the answer is wrong, check retrieval before you blame the model.**
- **Evals and guardrails aren't polish** – they separate a demo from production.
- **For agents, the stopping condition is decisive.**

### One thing to do today

Pick the **one** term you've been nodding along to without really understanding – and build the smallest possible version of it: a five-line RAG script, a single tool call, one eval that checks one thing. Twenty minutes of building teaches more than another hour of reading.

---

## Part 2: OpenKubes-specific – *in its own document*

> This part is planned as a separate **OpenKubes Glossary** (clusters, tooling, ADR process, MCP/Rovo, etc.). It is not yet included in this page.

Planned categories in the OpenKubes Glossary:

| Category | Terms |
| --- | --- |
| Clusters & Infrastructure | ok-infra, ok-gpu, ok-mgmt, ok1-talos, Hetzner bare-metal, Talos |
| Networking & Storage | Cilium, Traefik, Longhorn |
| AI components at OK | Ollama, GPU nodes, pilot cluster |
| Tooling & Process | ADR-first, three-way review, okgraph.py, gh CLI |
| Integrations (MCP) | Rovo MCP (Jira/Confluence) |

---

## Sources & further reading

- Divy Yadav (2026): *12 AI Terms You Need to Know Before Calling Yourself an AI Engineer* – [Medium](https://medium.com/ai-engineering-simplified/12-ai-terms-you-need-to-know-before-calling-yourself-an-ai-engineer-e8750c4f69d1) (original article, expanded and adapted here for beginners)
- Anthropic (2025): *Effective context engineering for AI agents* – [anthropic.com/engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Anthropic (2024): *Contextual Retrieval* – [anthropic.com/engineering](https://www.anthropic.com/engineering/contextual-retrieval)
- Chroma (2025): *Context Rot: How Increasing Input Tokens Impacts LLM Performance* – [research.trychroma.com](https://research.trychroma.com/context-rot)
