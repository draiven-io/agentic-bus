# Liquid Interfaces: A Dynamic Ontology for

# the Interoperability of Autonomous Systems

### Dhiogo José Correa de Sá∗ Carlos Pereira Lopes Filho†

### Carlos Eduardo Schmiedel‡

### 2026

```
Abstract
Contemporary software architectures struggle to support autonomous agents
whose reasoning is adaptive, probabilistic, and context-dependent, while sys-
tem integration remains dominated by static interfaces and deterministic con-
tracts. This paper introduces Liquid Interfaces, a coordination paradigm in
which interfaces are not persistent technical artifacts, but ephemeral relational
events that emerge through intention articulation and semantic negotiation at
runtime.
We formalize this model and present the Liquid Interfaces Protocol,
which governs intention-driven interaction, negotiated execution, and enforced
ephemerality under semantic uncertainty. We further discuss the governance
implications of this approach and describe a reference architecture that demon-
strates practical feasibility. Liquid Interfaces provide a principled foundation
for adaptive coordination in agent-based systems.
```
Keywords: Liquid Interfaces; Intention Based Computing; autonomous agents;
Semantic Interoperability; Software Architecture; Communication Protocols.

## 1 Introduction

The history of system integration is fundamentally a chronicle of attempts to impose
order upon informational chaos. From nascent Remote Procedure Call (RPC) proto-
cols Birrell and Nelson [1984] to the ubiquity of REST Fielding [2000] and GraphQL
∗dhiogo.correa@draiven.io
†carlos.lopes@draiven.io
‡carlos.schmiedel@draiven.io


Hartig and Pérez [2018], the overarching objective has been standardization. The
foundational premise of traditional Software Engineering posits that security and
efficiency are contingent upon predictability: System A must determine, with byte-
level precision, what System B anticipates receiving. This paradigm, codified by
Fielding’s architectural constraints Fielding [2000], has succeeded for decades, en-
abling the construction of robust, complex systems through explicit and immutable
contracts.

However, the integration of Large Language Models (LLMs) and Autonomous Agents
into enterprise workflows has precipitated a fundamental ontological dissonance
Zhang et al. [2025]. On one spectrum lies the liquid agent, which operates proba-
bilistically, interprets natural language, adapts to ambiguous contexts, and pursues
high-level objectives (e.g., “reduce logistics costs by 15% while maintaining deliv-
ery quality”) Xi et al. [2023]. On the other lies the “solid API,” which operates
deterministically, demands rigid syntax, and executes discrete functions (e.g., POST
/orders/v1/create with a predefined JSON schema). This friction is not merely
technical; it is ontological. As highlighted by recent research on tool-augmented
language models, the capability of agents to interact with external tools is often
constrained by the rigid structural requirements of existing interfaces Schick et al.
[2024].

Consider a practical scenario: an AI agent within a logistics firm must respond
to a storm that has closed a port. The agent perceives the disruption, yet the
legacy routing system’s API merely returns a static error: “Route Unavailable.” The
agent cannot negotiate alternatives; it lacks the protocol to converse with disparate
systems to synthesize a solution. It remains trapped in a deterministic impasse.
Consequently, a human operator must intervene, manually querying siloed systems,
negotiating with suppliers, and updating multiple platforms. What should be an
autonomous decision devolves into a costly, manual process.

The cost of translation between the agent’s fluid intent” and the API’s rigid form” has
emerged as the primary bottleneck for intelligent automation. The maintenance of
connectors, the synchronization of documentation (e.g., Swagger/OpenAPI), and the
management of breaking changes are symptomatic of a paradigm that has reached its
elastic limit. As noted in the context of machine learning systems, these integration
glues and schema dependencies contribute significantly to hidden technical debt,
compounding exponentially with each new system addition Sculley et al. [2015].

To transcend these limitations, we propose the Liquid Interfaces: a framework
that eschews static form as a prerequisite for interaction, privileging flow and intent.


Rather than rigid systems connected via static contracts, we propose a paradigm
wherein interfaces emerge dynamically, negotiated at runtime between agents that
may possess no prior history of interaction.

A Liquid Interfaces is not an endpoint, a contract, or a schema. It is a relational
event that manifests when two or more agents require collaboration. It arises from
necessity, stabilizes only for the required duration, and dissolves once its purpose is
fulfilled, leaving zero technical debt. In this model, the logistics agent could express
its intent: “I need to deliver this container within a 200km radius of the closed port,
optimizing for cost, time, and delivery quality.” The system would autonomously
discover which agents (warehouses, carriers, suppliers) could assist, negotiate terms,
and execute the solution—all without human intervention or pre-written integration
code.

This paper intentionally focuses on the conceptual, formal, and architectural foun-
dations of Liquid Interfaces. Concrete implementations, performance trade-offs, and
empirical evaluations are treated as separate concerns and are the subject of ongoing
and future work.

## 2 Theoretical Foundation and Related Work

Liquid Interfaces are proposed as an architectural response to the increasing het-
erogeneity, uncertainty, and volatility found in modern distributed computational
environments. While existing paradigms provide robust abstractions for integrating
well-defined services with stable contracts, they struggle in settings where partic-
ipants are unknown at design-time, capabilities evolve dynamically, and meaning
must be negotiated during execution. In such settings, static agreement mecha-
nisms become sources of friction rather than enablers of coordination.

### 2.1 Architectural Motivation

Most contemporary distributed systems assume that interacting components can
establish a stable representational contract prior to execution. Microservices, Ser-
vice Meshes, and API Gateways operate under this assumption by enforcing static
schemas, predefined endpoints, and lifecycle policies that support syntactic inter-
operability. Semantic Web technologies extend this premise into the semantic do-
main by attempting to align vocabularies through global ontologies and shared tax-
onomies. Agent Communication Languages (ACLs) further assume that interacting


agents share a common logical framework and can interpret performative acts within
that logic.

These architectures are effective when the system is closed, the interfaces are known
in advance, and the domain is sufficiently stable. However, their design assumptions
introduce friction in open-ended computational ecosystems in which (i) novel services
may appear without prior registration, (ii) capabilities may vary over time due to
learning or context, and (iii) goals may be situational rather than predetermined. In
these environments, static schemas and global ontologies impose upfront alignment
costs that scale poorly and reduce the flexibility of the agentic ecosystem.

### 2.2 Limits of LLM-Based Agentic Systems

Recent research demonstrates that Large Language Models (LLMs) can autonomously
plan, invoke tools, and orchestrate interactions across heterogeneous systems, ef-
fectively acting as general-purpose policy engines. While this represents a major
advance in agentic architectures, scaling LLMs does not eliminate several intrinsic
limitations. Recent theoretical work formalizes five such constraints Mohsin et al.
[2025], namely: (i) inevitable hallucination due to inherent approximation error, (ii)
context compression limitations that degrade reasoning over long inputs, (iii) brittle
reasoning emerging from likelihood-based training, (iv) retrieval fragility caused by
semantic mismatch between evidence and generation, and (v) multimodal misalign-
ment that undermines robust cross-signal grounding. Empirical studies corroborate
several of these phenomena: LLMs exhibit irreducible uncertainty even when con-
fident Kadavath et al. [2022], and their ability to exploit long contexts deteriorates
as distance from the query increases Liu et al. [2023].

These limitations have two consequences for open agentic ecosystems. First, they
imply that agentic systems cannot rely on deterministic correctness or complete
semantic grounding, even when augmented with planning or retrieval mechanisms.
Second, they indicate that LLMs can negotiate actions, but lack mechanisms for
negotiating interfaces or meaning under ambiguity, especially when semantic context
is asymmetrically distributed among participants. In other words, while LLMs can
decide what to do, they struggle to decide how to talk about what is being done
when no prior agreement exists.


### 2.3 Proposal: Liquid Interfaces

The Liquid Interfaces Protocol addresses this gap by shifting interface for-
mation from static contract definition to dynamic semantic negotiation. Instead of
requiring global agreement before execution, Liquid Interfaces enables autonomous agents to (i)
discover capabilities at runtime, (ii) negotiate intent without shared ontologies, (iii)
align meaning through iterative clarification, and (iv) dissolve interfaces once goals
are achieved. Under this perspective, interfaces are not stable artifacts but emergent
relational constructs optimized for adaptability during execution.

This reframing is relevant for ecosystems where the cost of prior semantic alignment
is prohibitive or where the domain shifts faster than global ontologies can be up-
dated. Liquid Interfaces do not replace existing contract-based architectures, but
complement them by enabling a spectrum of coordination modes ranging from fully-
static to fully-dynamic. Static contracts remain beneficial when stability is desired;
Liquid Interfaces become advantageous when flexibility is required.

### 2.4 Related Work and Differentiation

The proposed architecture situates itself at the intersection of several established
domains. While it draws upon foundational concepts from distributed systems and
semantic computing, it diverges fundamentally in its handling of uncertainty and
interface adaptability. Table 1 synthesizes the primary distinctions between tradi-
tional paradigms and the proposed Liquid Interfaces (Liquid Interfaces), delineating the specific
contributions of this work.


```
Table 1: Comparison with Traditional Approaches and Research Contributions
```
Research Area Traditional Approach Liquid Interfaces Contribu-
tion

Semantic Web &
Ontologies

```
Focuses on shared global vocab-
ularies (RDF, OWL) and static
ontology mapping to achieve a
universal truth Berners-Lee et al.
[2001].
```
```
Abandons the requirement for a
pre-agreed global lexicon, focus-
ing instead on run-time meaning
negotiation and the generation
of ephemeral, context-dependent
ontologies.
```
Microservices &
Service Mesh

```
Utilizes orchestrators (e.g., Ku-
bernetes) and meshes (e.g., Istio)
to manage syntactic communica-
tion between services with well-
defined APIs Posta and Malfer-
theiner [2023].
```
```
Operates at a higher level of
abstraction, orchestrating inten-
tions rather than services. The
interface is not a fixed endpoint,
but an emergent relational pact.
```
Agent Communi-
cation Languages
(ACL)

```
Defines rigid performative mes-
sage standards (e.g., FIPA-ACL)
for rational agents to interact
based on formal logic Foundation
for Intelligent Physical Agents
[2002].
```
```
Replaces formal logic with prob-
abilistic language models and
computational hermeneutics,
enabling interaction between
non-deterministic agents without
strict protocol compliance.
```
API Management
& Gateways

```
Centralizes access control and
routing based on static contracts
(OpenAPI/Swagger).
```
```
The Semantic Service Bus acts
not as a contract gatekeeper, but
as an ontological mediator facili-
tating dynamic capability discov-
ery and translation.
```
Smart Contracts
(Blockchain)

```
Automates the execution of im-
mutable, deterministic agree-
ments in a decentralized environ-
ment Buterin [2014].
```
```
Proposes ephemeral, adaptive
contracts that dissolve post-
execution. The focus is on agility
and negotiation rather than im-
mutability and trustless verifica-
tion.
```
Model Context
Protocol (MCP)

```
Standardizes the exposure of lo-
cal tools and context to LLMs,
answering the question “what is
available?” Anthropic [2024].
```
```
Complementary to MCP, it an-
swers “what should happen?”
by orchestrating intentions across
multiple agents. MCP provides
local technical contracts; Liquid Interfaces
governs global coordination.
```

Semantic Web aspires to global semantic convergence, whereas Liquid Interfaces enables local
reconciliation of meaning under partial knowledge. Service Meshes optimize syn-
tactic reliability between predefined components; Liquid Interfaces supports semantic discovery
and negotiation among heterogeneous autonomous agents. Classical ACLs assume
shared logical formalisms; Liquid Interfaces tolerates heterogeneous reasoning paradigms based
on probabilistic interpretation and contextual inference. Smart Contracts emphasize
immutability and determinism; Liquid Interfaces emphasize ephemerality and nego-
tiated action. Compared to the Model Context Protocol (MCP), which answers
“what is available?”, Liquid Interfaces answers “what should happen?” by orchestrating intent
across multiple agents.

These differences suggest that Liquid Interfaces occupy a complementary design
space situated between deterministic protocol engineering and open-ended agentic
negotiation.

### 2.5 Interpretive Lens

Although the proposal is technical in nature, it can also be situated within broader
interpretive frameworks that clarify the motivations behind its emergence and help
articulate its departure from traditional architectural paradigms. Bauman’s notion
of liquid modernity describes a socio-historical shift in which stable, durable, and in-
stitutionally enforced structures give way to arrangements characterized by fluidity,
adaptability, and temporary association Bauman [2000]. In Bauman’s analysis, the
“solid” phase of modernity was defined by an emphasis on planning, standardiza-
tion, and long-term institutional commitments, whereas the “liquid” phase privileges
flexibility, reconfiguration, and short-lived alignments that dissolve once they cease
to serve immediate purposes.

When interpreted computationally, this lens highlights the growing misalignment be-
tween rigid digital infrastructures—which operate through static contracts, global
ontologies, and pre-negotiated schemas—and contemporary computational ecosys-
tems that are increasingly open, heterogeneous, and fast-moving. Under this fram-
ing, architectural rigidity becomes a liability: just as Bauman observes that solid
structures struggle to persist under rapidly changing conditions, static computa-
tional protocols incur high coordination costs as system volatility increases. The
consequence is an impedance mismatch between the demands of the environment
and the affordances of the underlying architecture.

Gadamer’s concept of fusion of horizons offers a complementary perspective on
semantic negotiation. Rather than assuming that meaning is fixed or universally


shared, Gadamer posits that understanding emerges through dialogue between het-
erogeneous actors, each bounded by its own horizon of assumptions, intentions, and
capabilities Gadamer [1960]. Liquid Interfaces adopt a similar stance by allowing
interacting agents to converge on temporary semantic alignments without requiring
global ontological consensus.

Actor–Network Theory (ANT) Latour [2005] further extends this view by collapsing
the classical subject–object distinction and treating both human and non-human
entities as actants embedded within sociotechnical assemblages whose stability is not
given, but continuously negotiated through association. Under this interpretation,
the interface becomes a momentary pact that sustains coordination, dissolving once
the underlying relations no longer hold.

These conceptual lenses are not prerequisites for implementation, nor do they con-
stitute the core technical contribution of Liquid Interfaces. Rather, they provide
a vocabulary that makes explicit why architectures oriented around runtime ne-
gotiation, semantic adaptability, and ephemeral coordination become desirable as
computational ecosystems transition from closed, highly structured environments to
open, heterogeneous, and rapidly shifting ones.

## 3 Formal Definition: From Object to Event

The transition from the solid to the liquid paradigm represents an ontological shift
from static structural artifacts to dynamic temporal events. This section provides
the mathematical formalization of this transition, defining the Liquid Interfaces not
as a persistent boundary, but as a transient solution to a negotiation problem.

### 3.1 The Solid Paradigm: Static Contractual Isomorphism

In the classical paradigm, an interface Isolidis defined as a static contract enforcing
strict structural compliance. Let S be the universal set of possible schemas and
Σ⊂S be a specific, pre-defined schema. We define the solid interface as a tuple:

```
Isolid= (Σ,F,λ) (1)
```
Where:

- Σ represents the fixed data structure (ontology/schema).


- F is the set of permissible operations (endpoints/methods).
- λ : X →{ 0 , 1 } is a validation function (the contract enforcement).

The interaction is considered valid if and only if the input vector ⃗x satisfies the
strict compliance condition defined by Meyer’s Design by Contract principles Meyer
[1992]:

```
forall ̄x∈ Xinput, Valid( ̄x) ⇐⇒ ̄x∈ Dom(Σ)∧ λ( ̄x) = 1 (2)
```
Any deviation ∆ = ̄x\ Σ where ∆̸=∅ results in a set-theoretic mismatch, triggering
a system exception. The complexity of integration grows linearly with the rigidity
of Σ, creating what we term "Coupling Hysteresis"—the resistance of the system to
conform to new input shapes without refactoring.

### 3.2 The Liquid Paradigm: Intentional Probabilistic Negotia-

### tion

A Liquid Interfaces is formally defined not as a stored object, but as a time-bounded
generative function. Let Φ denote the Intention (the semantic goal),Ctthe temporal
Context, and G the Governance constraints.

We posit that a Liquid Interfaces Iliquidis the output of a negotiation function N
executed at time t 0 :

```
Iliquid(t) =N (Aemitter,Areceiver, Φ,Ct) subject to G (3)
```
Unlike Isolid, which demands structural equality, Iliquid seeks **Semantic Equiva-
lence**. The function N operates as an optimization process that minimizes the
Semantic Entropy H(S) between the agents’ horizons:

```
minπ H(S) =−
```
#### X

```
k
```
```
p(mk| Φ,Ct) logp(mk| Φ,Ct) (4)
```
Where π is the generated protocol (the temporary interface) and p(mk) is the prob-
ability that message mkcorrectly fulfills intention Φ.


### 3.3 Temporal Ephemerality and Debt Cancellation

A defining characteristic of the Liquid Interfaces is its lifecycle. While Isolidpersists
indefinitely (∆t → ∞), Iliquidis strictly ephemeral. We define the existence of the
interface as a function of the interaction window W:

```
∃Iliquid(t) ⇐⇒ tstart≤ t≤ tack (5)
```
At t > tack(post-execution), the interface structure π dissolves. Mathematically,
this implies that the Residual Coupling (Rc) between Agent A and Agent B becomes
zero:

```
∀t > tack, Rc(A,B) = 0 (6)
```
This formalizes the claim that Liquid Interfaces do not accumulate technical debt,
as no static schema remains to be maintained or versioned. The "integration" is
re-instantiated ab initio for every new intention, ensuring maximum plasticity.

## 4 Protocol and System Architecture

To instantiate the Liquid Interfaces paradigm, we define a protocol specification
and a coordination architecture that concretely realizes intention-driven interaction,
semantic negotiation, and ephemeral interface life cycles within distributed systems.
The reference architecture presented here is illustrative rather than prescriptive. It
demonstrates feasibility without constraining valid implementations of the protocol.

Rather than encoding fixed call semantics or static service contracts Fielding [2000],
the proposed architecture treats interaction as a temporally bounded coordination
process among autonomous agents operating under uncertainty. The protocol defines
a small set of coordination invariants—intent-first interaction, negotiated agreement
before execution, and mandatory dissolution—while leaving matching, authorization
policies, and conflict resolution strategies as replaceable policy choices.

Consequently, Liquid Interfaces is not intended to replace low-latency deterministic RPC or real-
time control protocols, but to support coordination under semantic uncertainty in
open agent environments.


### 4.1 Liquid Interfaces Protocol

The Liquid Interfaces Protocol defines a coordination model through which in-
terfaces emerge, stabilize, and dissolve as a consequence of goal-directed interaction
among autonomous agents. In contrast to conventional request–response proto-
cols and message-oriented agent standards, Liquid Interfaces treats interaction as a negotiated,
intention-driven process rather than as the invocation of predefined operations.

At its core, Liquid Interfaces governs how agents articulate intentions, expose capabilities, nego-
tiate terms of collaboration, and coordinate execution under semantic uncertainty.
The protocol privileges semantic alignment over syntactic compliance, allowing in-
teraction to proceed without pre-established schemas, fixed endpoints, or globally
shared ontologies.

Liquid Interfaces is realized over persistent bidirectional communication channels and enforces a
constrained interaction structure that ensures progress while preserving interpretive
flexibility. Execution is permitted only after sufficient semantic agreement has been
established, and all coordination artifacts are explicitly dissolved upon task comple-
tion, thereby enforcing ephemerality as a protocol-level invariant. This approach de-
parts from traditional interface-centric integration models by treating coordination
itself as a first-class, transient construct Fielding [2000], Foundation for Intelligent
Physical Agents [2002].

4.1.1 Message Semantics, Interaction Lifecycle, and Ephemerality

All protocol messages in Liquid Interfaces are represented as structured JSON documents and
are categorized by a message_type field that determines their semantic role within
an interaction. Message types are not merely communicative primitives, but perfor-
mative acts that collectively define the lifecycle of a Liquid Interfaces.

The core message types are:

- intent: articulates a high-level objective and instantiates a new interaction
    context, giving rise to a Liquid Interfaces;
- offer: declares the availability of a capability relevant to the expressed inten-
    tion, potentially constituting a total or partial contribution toward its fulfill-
    ment;
- accept / reject: signal negotiated agreement or refusal, contributing to the
    stabilization or revision of the interaction context;


- execute: authorizes coordinated execution under the negotiated terms;
- complete: signals termination of execution, independent of success or failure;
- dissolve: explicitly invalidates the interaction context and triggers mandatory
    cleanup of all coordination artifacts.

A Liquid Interfaces is defined as a temporally bounded coordination construct whose
existence is contingent upon an active interaction context. Its lifecycle is not prede-
termined by static configuration, but emerges dynamically through the articulation
of intent and subsequent semantic negotiation.

An interface is instantiated when an agent expresses an intention and at least one
counterparty acknowledges semantic relevance. Stabilization does not imply com-
mitment to a single executing agent; agreement may bind multiple partial offers
into a composite execution structure whose coordinated application satisfies the de-
clared intention.Execution is explicitly conditioned on this stabilization and may be
aborted or renegotiated in response to failure, constraint violation, or withdrawal of
consent.

Upon completion or abandonment of execution, a dissolve message enforces ephemer-
ality by invalidating all coordination artifacts, including negotiated agreements, au-
thorization scopes, and execution bindings. No residual interface structures persist
beyond this point.

By defining lifecycle semantics through message meaning rather than explicit control
states, Liquid Interfaces treats interfaces as transient coordination events rather than persistent
integration artifacts. This explicit instantiation and mandatory dissolution prevent
the accumulation of long-lived coupling and preserve the protocol’s commitment to
minimal residual state.

Beyond execution semantics, Liquid Interfaces presupposes a layered substrate that supports
semantic coordination, transport delivery, cryptographic identity, and physical de-
ployment. Figure 1 illustrates this reference stack, while Figure 2 summarizes the
lifecycle of a Liquid Interfaces as instantiated through the protocol’s performative
message types. The interface emerges upon articulation of intent, stabilizes through
negotiation, executes under the negotiated terms, and is mandatorily dissolved at
the end of the session, ensuring no persistent coordination artifacts remain beyond
the interaction context.


```
Application-Level Agents & Business Logic
Autonomous agents exposing capabilities and intentions
```
```
Liquid Interfaces Protocol Coordination Layer
Intent, discovery, negotiation, claim-based authorization, dissolution
```
```
Transport Layer
WebSockets / QUIC / gRPC / MCP; bidirectional message delivery
```
```
Cryptographic Identity & Claims
Enrollment, challenge–response, claims, signatures
```
```
Infrastructure Layer
Compute cluster, mesh, federation / WAN substrate
```
Figure 1: Reference stack underlying the Liquid Interfaces Protocol, illustrat-
ing the separation between semantic coordination, transport delivery, cryptographic
identity, and infrastructure substrate.

```
Figure 2: Macro-architecture of the Liquid Interfaces Protocol.
```

4.1.2 Semantic Capability Matching via LLM Adjudication

Semantic capability matching in the Liquid Interfaces Protocol is formulated as a
decision problem under uncertainty, rather than as a purely retrieval-based similarity
task. Given an expressed intention Φ, a contextual state Ct, and a set of declared
agent capabilities {ci}, the coordination layer must determine which agents are
semantically and operationally compatible with the intended objective.

In the current instantiation, this decision is performed through an LLM-based se-
mantic adjudicator. The adjudicator is provided with a structured representation of
the intention, contextual constraints, and capability descriptions, and is tasked with
producing an ordered set of candidate agents along with an explicit acceptability
judgment for each candidate. The adjudication process evaluates not only topical
relevance, but also constraint satisfiability, implicit dependencies, and contextual
alignment.

Formally, the adjudicator implements a probabilistic decision function:

```
fLLM: (Φ,Ct,{ci})→{(ci,si,ri)} (7)
```
where si∈ [0, 1] denotes the estimated suitability score of capability cifor fulfilling
intention Φ, and riis a structured justification trace describing the rationale for the
decision.

Candidates whose suitability scores exceed a configurable threshold are admitted
into the negotiation phase, while others are excluded. This mechanism enables the
coordination layer to reason over unstructured and partially specified capabilities,
supporting interaction between agents with no prior coordination history.

By framing matching as semantic adjudication rather than lexical similarity, the
protocol accommodates ambiguity, conflicting constraints, and underspecified objec-
tives—properties that are intrinsic to real-world coordination problems. Moreover,
the adjudicator abstraction remains orthogonal to the protocol itself, allowing alter-
native instantiations (e.g., embedding-based retrieval or hybrid pipelines) without
altering the interaction semantics defined by Liquid Interfaces.

Recent work has demonstrated that large language models can act as semantic
evaluators and decision layers in tool-augmented and agentic systems, supporting
reasoning over constraints and action feasibility Schick et al. [2024], Yao et al. [2023],
Xi et al. [2023].

In addition to semantic adjudication, Liquid Interfaces supports outcome-informed ranking as a


secondary signal for candidate selection. Historical interaction outcomes are used to
derive soft performance priors associated with individual agents, reflecting factors
such as successful task completion, response quality, and execution latency.

These priors do not override semantic compatibility, but bias the adjudication pro-
cess when multiple candidates exhibit comparable suitability. Formally, the adju-
dicator may incorporate an outcome-based prior ρifor each capability ci, learned
from past interactions, such that:

```
s′i= α· si+ (1− α)· ρi (8)
```
where si denotes the semantic suitability score produced by the adjudicator, ρi
represents the normalized historical performance prior, and α ∈ [0, 1] controls the
relative influence of semantic alignment versus empirical outcome.

Outcome priors may be derived from multiple signals, including execution success,
response consistency, explanation coherence, and interaction latency, and are up-
dated incrementally over time. By design, these priors remain advisory rather than
deterministic, ensuring that agents are not permanently penalized for transient fail-
ures and that novel or infrequently used agents remain discoverable.

This mechanism allows Liquid Interfaces to balance semantic intent alignment with empirical
performance, enabling adaptive coordination without introducing static trust hier-
archies or persistent coupling.

4.1.3 Failure Handling and Renegotiation

Failure is treated in Liquid Interfaces as an expected and informative outcome of coordination,
rather than as an exceptional condition. Given the open and semantically uncertain
nature of agent interactions, failures may arise from unavailable capabilities, un-
satisfied constraints, insufficient authorization scopes, or execution-time conditions
beyond the control of any single participant.

Rather than terminating the interaction upon failure, Liquid Interfaces allows failure signals
to trigger renegotiation. When execution cannot proceed or complete under the
negotiated terms, agents may revise constraints, withdraw offers, or propose alter-
native capabilities without invalidating the interaction context. In this sense, failure
functions as a coordination signal that prompts semantic realignment rather than
protocol-level abort.

Failure handling preserves the protocol’s core invariants: execution is never per-


mitted without sufficient agreement, and no partial or ambiguous outcomes are
committed as stable interface artifacts. If renegotiation does not yield a viable
configuration, the interaction is explicitly dissolved, ensuring that no residual state
persists beyond the failed attempt.

By elevating failure to a first-class semantic event, Liquid Interfaces supports resilient coordina-
tion under uncertainty while avoiding exception-driven control flow and long-lived
error states common in request–response integration models.

4.1.4 Security and Authorization

Security in the Liquid Interfaces Protocol is defined at the level of agent interac-
tion, independent of any specific coordination infrastructure. The protocol adopts
a layered security model suitable for open multi-agent environments, where partic-
ipants may have no prior trust relationship and interaction contexts are inherently
ephemeral.

Agent authentication follows a two-phase process: enrollment and authentication.
During enrollment, an agent requests registration by submitting a public key that
uniquely represents its cryptographic identity. Upon acceptance, this public key is
recorded as the persistent identifier of the agent within the protocol context.

Subsequent authentication is performed through a challenge–response mechanism.
When an agent initiates a new interaction, the coordinating party issues a cryp-
tographic challenge that must be signed using the agent’s private key. Successful
verification establishes agent authenticity without disclosure of secret material, en-
suring resistance to replay and impersonation attacks.

Beyond identity verification, the protocol enforces message-level integrity by re-
quiring cryptographic signatures on semantically binding messages (e.g., accept,
execute, complete), thereby providing non-repudiation and preserving the integrity
of negotiated agreements.

Authorization in Liquid Interfaces is modeled as a claim-based, policy-governed process rather
than as a static access-control list. Agents may declare (claim) authorization scopes
representing the classes of actions or capabilities they intend to exercise. These
claims are evaluated against organizational-defined authorization policies before be-
ing approved for participation in the negotiation or execution phases.

Authorization scopes are limited to the interaction context and may be constrained
by organizational boundaries, agent roles, trust levels, or contextual conditions.
Approved scopes grant permission to engage in specific categories of coordination


actions but do not constitute permanent privileges. All authorization grants are
explicitly bound to the lifetime of the interaction and are revoked upon dissolution.

This authorization model aligns with previous work on capability and claim-based
security in distributed systems, while extending these concepts to semantically ne-
gotiated and ephemeral interaction contexts Lampson et al. [1992].

## 5 The Logic of Ephemeral Coordination

To operationalize the transition from static interfaces to liquid coordination, we
define the Liquid Interfaces Protocol not as a software artifact, but as a set
of architectural invariants and logical constraints governing agent interaction under
semantic uncertainty. In this respect, Liquid Interfaces plays a role analogous to the constraint-
based formulation of REST, which defined the architectural properties of the Web
without prescribing specific implementations Fielding [2000].

Rather than validating interactions through syntactic conformance alone, Liquid Interfaces char-
acterizes coordination as a bounded, goal-directed process whose validity depends
on semantic alignment, negotiated agreement, and enforced ephemerality. This sec-
tion formalizes the core coordination invariants, the negotiation function, and the
boundary conditions that preserve system safety when semantic negotiation fails.

### 5.1 Coordination Invariants

A system may be classified as implementing a Liquid Interfaces if and only if it
satisfies the following coordination invariants. These constraints are intentionally
negative: they restrict classes of behavior that would otherwise reintroduce static
coupling or long-lived integration debt.

5.1.1 Invariant I: Intentional Primacy

In conventional interface-driven architectures, interaction validity is determined by
syntactic compliance: V (x) ⇐⇒ x∈ Σ. In contrast, Liquid Interfaces defines validity relative to
the declared intention Φ. An interaction step is considered valid only if it advances
semantic alignment with respect to that intention.

Formally, let H(S) denote the entropy of the shared semantic state between two
agents. An interaction step at time t is valid if and only if:


```
∆H(S) = H(S)t− H(S)t+1> 0 (9)
```
where ∆H(S) = H(S)t−H(S)t+1, so a positive value indicates reduced uncertainty.

That is, the interaction must reduce semantic uncertainty rather than merely satisfy
structural constraints. Messages that are syntactically valid but fail to improve
semantic alignment are treated as coordination failures, triggering clarification or
renegotiation rather than execution. This reframes error handling as a semantic
breakdown rather than a protocol exception Gadamer [1960].

5.1.2 Invariant II: Mandatory Temporal Dissolution

A defining property of liquid coordination is the prohibition of persistent interface
structures. Any negotiated interface Iliquidis strictly bound to the temporal window
of the interaction:

```
∃Iliquid(t) ⇐⇒ tstart≤ t≤ tack (10)
```
Upon completion or abandonment of execution at tack, all negotiated schemas, au-
thorization scopes, and execution bindings are invalidated. Persistence of these
artifacts beyond the interaction window constitutes a violation of the protocol.

This invariant prevents the gradual accumulation of implicit contracts and stale
assumptions, enforcing ephemerality as a first-class coordination property rather
than an implementation detail Lehman [1980].

5.1.3 Invariant III: Bounded Residual Coupling

To preserve loose coupling under repeated interaction, Liquid Interfaces constrains the resid-
ual dependency between agents across coordination episodes. Let Rc(A,B) denote
the residual coupling induced by prior interactions between agents A and B. Liquid Interfaces
requires that:

```
∀t > tack, Rc(A,B) = 0 (11)
```
This invariant does not forbid learning or adaptation, but prohibits the reuse of
previously negotiated interface structures as binding assumptions. Each interaction
must be renegotiated, ensuring robustness against concept drift, capability evolution,
and contextual change Latour [2005].


5.1.4 Invariant IV: Composable Intent Resolution

Liquid coordination does not require that a single agent satisfies a declared inten-
tion. An intention Φ can be resolved through the composition of multiple partial
capabilities, potentially contributed by distinct agents, provided that their ordered
execution advances semantic alignment with respect to Φ.

Formally, let Φ 1 ,..., Φndenote a set of sub-intentions such that their sequential or
partially ordered execution reduces semantic entropy relative to the original inten-
tion:

```
Xn
i=
```
```
∆H(Si) > 0 =⇒ Φ is resolvable (12)
```
Agreement under Liquid Interfaces is reached over the composite execution structure as a whole,
rather than over individual steps in isolation. Partial acceptance of constituent
capabilities does not authorize execution; execution is permitted only after atomic
agreement on the full composition.

This invariant guaranties that multi-agent coordination emerges from negotiated
capability composition rather than centralized orchestration, while preserving the
ephemeral and decoupled nature of liquid interfaces.

### 5.2 The Negotiation Function

The core operational mechanism of Liquid Interfaces is the negotiation function N , which syn-
thesizes a temporary coordination structure at runtime. Rather than retrieving
predefined interfaces,N generates a provisional protocol π that minimizes semantic
uncertainty subject to contextual and governance constraints.

```
Iliquid=N (Φ,C,G) = arg minπ
```
#### (

#### X

```
k
```
```
−p(mk| Φ) logp(mk| Φ) : π |=G
```
#### )

#### (13)

Here, p(mk | Φ) denotes the estimated probability that message structure mk ad-
vances satisfaction of the declared intention. Negotiation proceeds iteratively until
semantic confidence exceeds a predefined safety threshold τ, at which point execu-
tion may commence.


### 5.3 Boundaries of Liquidity and Deterministic Fallbacks

A complete theory of liquid coordination must explicitly account for failure modes.
We define the boundary of liquidity as the point at which semantic negotiation fails
to converge within acceptable temporal or uncertainty bounds.

5.3.1 Entropy Threshold

Let H(S) denote the semantic entropy of the shared interpretive state and let tstart
be the initial negotiation time. The initial entropy is defined as:

```
H 0 = H(S)
```
(^)
t=tstart.^ (14)
To ensure that semantic negotiation converges within acceptable bounds, we define
a tolerance parameter τ ∈ (0, 1) representing the minimum required fractional re-
duction in entropy for negotiation to succeed. The maximum admissible entropy is
thus:
Hmax= (1− τ )H 0. (15)
Negotiation proceeds iteratively for at most nmaxsteps. The liquid state is considered
unstable if no iteration achieves entropy below the admissible threshold:
∀n≤ nmax, H(S)n> Hmax =⇒ TriggerFallback. (16)
This condition identifies a formal boundary at which interpretive flexibility becomes
detrimental to liveness. For example, setting τ = 0. 5 requires negotiation to reduce
entropy by at least 50% of its initial value. Domain-specific safety policies may
instead choose τ based on minimum semantic confidence required for the application
domain.
5.3.2 Fallback Modes
Upon crossing the boundary of liquidity, Liquid Interfaces mandates deterministic reversal. Two
fallback modes are defined:

1. Recursive Simplification: The protocol retries negotiation with a simplified
    intention Φ′⊂ Φ or an expanded context C′, analogous to human rephrasing
    in cooperative dialogue.


2. Solidification: The protocol abandons semantic negotiation and anchors in-
    teraction to a minimal, pre-agreed core ontology Σcore, ensuring deterministic
    execution of critical actions.

By explicitly defining these boundaries, Liquid Interfaces treats liquidity as a bounded and gov-
erned coordination regime rather than an unconstrained source of nondeterminism.

## 6 Governance Implications of Liquid Interfaces

The introduction of Liquid Interfaces has direct implications for how governance, se-
curity, and accountability are expressed in distributed systems. By elevating intent,
negotiation, and semantic agreement to first-class protocol constructs, Liquid Interfaces enables
governance mechanisms that operate at the level of meaning rather than at the level
of static interfaces or predefined operations.

This section discusses the governance properties implied by the protocol, focusing
on intention-based authorization, semantic auditability, and threat mitigation prin-
ciples inherent to liquid coordination.

### 6.1 Intention-Based Governance

Traditional access-control models such as Role-Based Access Control (RBAC) and
Attribute-Based Access Control (ABAC) authorize discrete operations against pre-
defined resources. In contrast, Liquid Interfaces enable an Intention-Based Access
Control (IBAC) model, in which governance decisions are evaluated against the
expressed intent, its contextual constraints, and organizational policies.

Under IBAC, authorization is decoupled from concrete execution paths. Policies are
applied prior to negotiation and execution, allowing organizations to govern what
is being attempted rather than how it is technically realized. This shift enables con-
sistent enforcement of business rules and compliance constraints even as execution
plans, participating agents, or capabilities vary dynamically.

By aligning authorization with intent rather than endpoints, IBAC supports adap-
tive governance in environments characterized by semantic uncertainty and evolving
coordination patterns.

This perspective builds on prior work that treats coordination as distinct from com-
putation, extending it into the domain of governance and access control under se-
mantic uncertainty Papadopoulos and Arbab [1998].


### 6.2 Semantic Auditability

Because Liquid Interfaces treats intention articulation, negotiation, and execution as explicit
protocol events, it enables a form of auditability that extends beyond traditional
request–response logging. Instead of recording only syntactic operations, liquid
interactions preserve the semantic context and rationale underlying coordination
decisions.

Semantic auditability allows post-hoc reconstruction of why a particular coordina-
tion outcome was reached, including the evaluated intent, negotiated terms, ap-
plied policies, and observed outcomes. This property is critical for accountability,
regulatory compliance, and incident analysis in autonomous and semi-autonomous
systems.

By capturing reasoning context rather than isolated actions, Liquid Interfaces provides a foun-
dation for explainable governance in agent-mediated environments.

This form of auditability aligns with interpretive views of action and decision-
making, in which meaning and context are inseparable from execution Winograd
and Flores [1986].

### 6.3 Threat Model Considerations

The open and dynamic nature of liquid coordination introduces threat vectors that
differ from those of traditional interface-centric systems. These include malicious
capability claims, adversarial intent formulation, replay of negotiation messages, and
attempts to exploit partial semantic agreement.

Liquid Interfaces addresses these risks through a combination of protocol-level principles: cryp-
tographic identity binding, semantic validation of intents and capabilities, message-
level integrity, and explicit lifecycle enforcement. Importantly, failure and renegotia-
tion are treated as first-class outcomes, reducing reliance on exception-driven control
flow that may otherwise amplify attack impact.

Mandatory dissolution of interaction contexts further limits the persistence of com-
promised coordination artifacts, constraining the blast radius of adversarial behav-
ior. As a result, governance in Liquid Interfaces emphasizes containment, revocability, and se-
mantic validation over static perimeter defenses.

These mitigation principles are consistent with foundational security design princi-
ples such as least privilege, fail-safe defaults, and containment Saltzer and Schroeder
[1975].


### 6.4 Governance as a Consequence of Coordination

Taken together, these properties position governance in Liquid Interfaces not as an
external control layer, but as an emergent consequence of semantically mediated
coordination. Authorization, auditability, and risk mitigation arise from the same
protocol mechanisms that enable negotiation and execution, preserving coherence
between governance objectives and operational behavior.

This integration allows organizations to govern autonomous agent interactions with-
out reintroducing rigid interface contracts, maintaining alignment between liquid
coordination and institutional accountability.

This view is consistent with sociotechnical perspectives in which governance and
stability emerge from networks of interaction rather than from centralized control
structures Latour [2005].

## 7 Limitations and Open Challenges

While Liquid Interfaces address fundamental limitations of static integration paradigms,
the proposed model deliberately introduces a different set of trade-offs. The con-
straints discussed in this section are not incidental shortcomings of the protocol,
but intrinsic boundaries arising from the choice to treat coordination as a semantic,
intention-driven process rather than as a deterministic interface invocation mecha-
nism. As such, they delineate the regimes in which liquid coordination is appropri-
ate, as well as the open challenges that emerge from this reframing.

### 7.1 Paradigm Boundaries

Liquid Interfaces prioritize semantic flexibility, adaptive negotiation, and contextual
interpretation over deterministic execution guarantees. Consequently, the paradigm
is not suitable for domains that require strict real-time constraints, bounded worst-
case latency, or hard safety guarantees enforced through static verification. Co-
ordination mechanisms grounded in semantic negotiation inherently introduce de-
liberative overhead that cannot be eliminated without reverting to rigid interface
contracts.

Moreover, Liquid Interfaces are designed for environments characterized by seman-
tic uncertainty, evolving capabilities, and open-ended interaction. In domains gov-
erned by stable ontologies, well-defined schemas, and long-lived contracts, tradi-


tional interface-centric architectures may offer superior efficiency and predictability.
In such settings, the overhead of dynamic negotiation may outweigh its benefits.

Finally, by shifting governance from static artifacts to contextual evaluation, the
protocol may conflict with regulatory or organizational environments that mandate
immutable contracts or pre-certified execution paths. Reconciling ephemeral coor-
dination with such compliance requirements remains an open challenge and may
require hybrid architectures that combine liquid negotiation with selectively solidi-
fied execution cores.

### 7.2 Coordination Trade-offs

The reference architecture discussed in this work adopts a logically centralized coor-
dination substrate to simplify semantic mediation and negotiation ordering. While
centralization is not a requirement of the Liquid Interfaces Protocol itself, fully decen-
tralized or federated realizations introduce additional complexity related to semantic
consistency, policy enforcement, and negotiation convergence.

In particular, decentralized coordination raises challenges in maintaining coherent
semantic adjudication across heterogeneous agents, especially when contextual in-
formation is unevenly distributed. Designing coordination substrates that preserve
the protocol’s semantic invariants without reintroducing rigid coupling or centralized
control remains an open research direction.

### 7.3 Trust and Capability Verification

Liquid Interfaces rely on agents declaring capabilities and constraints as part of the
negotiation process. While cryptographic identity binding ensures agent authentic-
ity, it does not guarantee the veracity or completeness of declared capabilities. As
a result, liquid coordination introduces a tension between openness and trust.

Mechanisms for capability verification, reputation modeling, and adversarial re-
silience must balance robustness against the protocol’s commitment to semantic
flexibility and low coupling. Overly strict verification risks excluding novel or in-
frequently interacting agents, while overly permissive policies may enable strategic
misrepresentation or exploitation of partial semantic agreement.

Designing verification and trust mechanisms that remain advisory rather than deter-
minative—thereby avoiding the reintroduction of static trust hierarchies—remains
an unresolved challenge.


### 7.4 Dynamic Context and Renegotiation

The protocol treats failure and renegotiation as first-class coordination outcomes.
However, dynamic changes in context during execution—such as shifting constraints,
partial fulfillment of intentions, or external environmental changes—raise questions
about when renegotiation should be triggered and how existing agreements should
be revised.

Establishing principled criteria for renegotiation without introducing excessive co-
ordination overhead or oscillatory negotiation cycles is an important area for future
work. These challenges are inherent to any coordination regime that operates under
semantic uncertainty and cannot be fully resolved through static protocol design.

### 7.5 Scope of Applicability

Liquid Interfaces are not intended as a universal replacement for conventional in-
tegration mechanisms. Rather, they define a coordination regime optimized for
interaction under semantic uncertainty among heterogeneous autonomous agents.

Identifying hybrid architectures in which liquid coordination coexists with static
interfaces—and determining appropriate boundaries between dynamic negotiation
and deterministic execution—remains an open research direction. Such hybrids are
likely to be essential for practical adoption, enabling systems to selectively exploit
liquidity where adaptability is required while retaining solid interfaces where stabil-
ity and efficiency dominate.

## 8 Conclusion

This work introduced the concept of Liquid Interfaces as a fundamental reframing of
system integration in the presence of autonomous agents and semantic uncertainty.
Rather than treating interfaces as static contracts between predefined endpoints, we
proposed an interaction model in which interfaces emerge dynamically as transient
coordination events, negotiated at runtime and dissolved upon task completion.

Grounded in sociological, philosophical, and computational foundations, the Liquid
Interface Protocol formalizes this paradigm through intention-driven interac-
tion, semantic adjudication, negotiated agreement, and enforced ephemerality. By
elevating intent, negotiation, and reasoning to first-class protocol constructs, Liquid Interfaces en-
ables coordination among heterogeneous agents without requiring shared ontologies,


rigid schemas, or long-lived integration artifacts.

We further examined the governance implications of this shift, showing how intention-
based authorization, semantic auditability, and lifecycle-bound coordination allow
accountability and control to emerge from the same mechanisms that enable adaptive
interaction. In contrast to interface-centric security models, governance in Liquid
Interfaces operates at the level of meaning and context, preserving flexibility without
sacrificing oversight.

Taken together, Liquid Interfaces represent a move away from integration as infras-
tructure and toward coordination as a semantic process. This perspective challenges
long-standing assumptions in software engineering, particularly the equation of re-
liability with rigidity, and opens new directions for the design of agent-mediated
systems capable of operating under ambiguity, change, and incomplete knowledge.

As autonomous agents become increasingly embedded in organizational and so-
ciotechnical environments, the ability to coordinate without static coupling will
become essential. Liquid Interfaces offer a principled foundation for this transition,
inviting further exploration into decentralized realizations, verification mechanisms,
and hybrid architectures that combine liquid coordination with conventional sys-
tems.

## References

Anthropic. Model context protocol (mcp): An open standard for connecting ai as-
sistants to systems. https://modelcontextprotocol.io, 2024. Accessed: 2024-
12-30.

Zygmunt Bauman. Liquid Modernity. Polity Press, Cambridge, UK, 2000. ISBN
978-0745624099.

Tim Berners-Lee, James Hendler, and Ora Lassila. The semantic web. Scientific
American, 284(5):34–43, 2001.

Andrew D. Birrell and Bruce J. Nelson. Implementing remote procedure calls. ACM
Transactions on Computer Systems, 2(1):39–59, 1984.

Vitalik Buterin. A next-generation smart contract and decentralized application
platform. Ethereum White Paper, 2014. URL https://ethereum.org/en/
whitepaper/.


Roy Thomas Fielding. Architectural Styles and the Design of Network-Based Soft-
ware Architectures. PhD thesis, University of California, Irvine, 2000.

Foundation for Intelligent Physical Agents. Fipa acl message structure specification.
[http://www.fipa.org/specs/fipa00061/,](http://www.fipa.org/specs/fipa00061/,) 2002. Standard SC00061G.

Hans-Georg Gadamer. Truth and Method. Bloomsbury Academic, London, UK,

1960. ISBN 978-0826476975. Translation revised by J. Weinsheimer and D. G.
Marshall (2004).

Olaf Hartig and Jorge Pérez. Semantics and complexity of graphql. In Proceedings
of the 2018 World Wide Web Conference, pages 1155–1164, 2018.

S. Kadavath et al. Language models (mostly) know what they know. arXiv preprint
arXiv:2207.05221, 2022.

Butler Lampson, Martín Abadi, Michael Burrows, and Edward Wobber. Authentica-
tion in distributed systems: Theory and practice. ACM Transactions on Computer
Systems, 1992.

Bruno Latour. Reassembling the Social: An Introduction to Actor-Network Theory.
Oxford University Press, Oxford, UK, 2005. ISBN 978-0199256044.

Manny M. Lehman. Programs, life cycles, and laws of software evolution. Proceedings
of the IEEE, 68(9):1060–1076, 1980. doi: 10.1109/PROC.1980.11805.

Nelson Liu et al. Lost in the middle: How language models use long contexts. arXiv
preprint arXiv:2307.03172, 2023.

Bertrand Meyer. Eiffel: The Language. Prentice Hall, Hemel Hempstead, 1992.
ISBN 978-0132479257. Foundational work on Design by Contract.

Muhammad Ahmed Mohsin et al. On the fundamental limits of llms at scale, 2025.

George A. Papadopoulos and Farhad Arbab. Coordination models and languages.
In M. V. Zelkowitz, editor, Advances in Computers, volume 46, pages 329–400.
Academic Press, New York, NY, USA, 1998. doi: 10.1016/S0065-2458(08)60208-9.

Christian Posta and Rinor Malfertheiner. Istio in Action. Manning Publications,

2023. ISBN 978-1617295829.

Jerome H. Saltzer and Michael D. Schroeder. The protection of information in
computer systems. Proceedings of the IEEE, 1975.


Timo Schick et al. Toolformer: Language models can teach themselves to use tools.
Advances in Neural Information Processing Systems, 36, 2024.

David Sculley et al. Hidden technical debt in machine learning systems. Advances
in Neural Information Processing Systems, 28, 2015.

Terry Winograd and Fernando Flores. Understanding Computers and Cognition:
A New Foundation for Design. Addison-Wesley, Reading, MA, 1986. ISBN 978-
0201112979.

Zhiheng Xi et al. The rise and potential of large language model based agents. arXiv
preprint arXiv:2309.07864, 2023.

Shunyu Yao, Dian Yu, Jeffrey Zhao, Izhak Shafran, Thomas L. Griffiths, Yuan Cao,
and Karthik Narasimhan. Tree of thoughts: Deliberate problem solving with
large language models. arXiv preprint, arXiv:2305.10601, 2023. URL https:
//arxiv.org/abs/2305.10601.

Ke Zhang, Wei Liu, and Jian Chen. Self-organizing agent network for llm-based
workflow automation, 2025.