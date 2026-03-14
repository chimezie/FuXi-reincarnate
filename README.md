FuXi is a Python-based, bi-directional logical reasoning system for the semantic web.

It is being re-written for modern Python 3.9+ and changes are being made to the Fuxi-reincarnate-chimezie git repository.

At the heart of the python-dlp framework is an implementation of most of the RETE-UL algorithms outlined in the PhD thesis (1995) of Robert Doorenbos:

> Production Matching for Large Learning Systems.

Robert's thesis describes a modification of the original Rete algorithm that (amongst other things) limits the fact 
syntax (referred to as Working Memory Elements) to 3-item tuples (which corresponds quite nicely with the RDF abstract syntax). 
The thesis also describes methods for using hash tables to improve efficiency of alpha nodes and beta nodes.

Instances of the FuXi.Rete.ReteNetwork class are RETE-UL networks.

FuXi has full support for Sideways Information Passing, a general optimization technique originally based on one of the 
more important algorithms in database theory called the Generalized Magic Set (GMS) transformation. Originally, the GMS 
transformation is used to efficiently evaluate a query against a (possibly recursive) datalog program and database. It 
is the theoretical basis of relational algebra implementations which include (possibly recursive) views.

## Package Name

The canonical import name is `fuxi` (lowercase):

```python
import fuxi
from fuxi.Rete.Network import ReteNetwork
```

The legacy `FuXi` import path is still supported for backward compatibility but is deprecated and will emit a warning.

## Development Setup

Install uv if not already installed (via package manager preferred):

```bash
sudo zypper install uv
```

Create a virtual environment and install dependencies:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Details ##

#### Base and Derived Predicates #### 
An important distinction needed for FuXi's SIP capabilities is between derived predicates and base predicates, the 
former comprises the Intensional Database (IDB) and the latter the Extensional Database (EDB). Derived predicates are those 
that (as the name suggests) are derived via rules and base predicates are (in the traditional sense) the stated facts 
(also known as the database).

#### Backward Chaining / Top Down Evaluation #### 
FuXi comes with two top-down (backward chaining) algorithms for SPARQL RIF-Core and OWL 2 RL entailment. The first is a 
native Prolog-like Python implementation that can take a triple (as a goal) and generate a series of SPARQL queries 
against the given factGraph, combining the results as answers to the goal. This has been deprecated by an extension of the 
Backwards Fixpoint Procedure, a 'meta-interpretation' method that creates a program or ruleset that captures (or encodes) 
a top-down procedure for answering the original question such that it can be evaluated via a 
forward-chaining / bottom-up algorithm.

Both of these methods can be used to answer queries that involve derived predicates whose semantics are defined either 
in a set of OWL2 RL axioms or RIF Core formulas. These answers are computed via a series of coordinated SPARQL queries 
dispatched against the user-specified RDF graph (which can be connected to a large, remote SQL backend).

#### Reason for Deprecation #### 
The FuXi.Rete.TopDown module is essentially a refutation (proof)-based implementation of a top-down strategy. Adding 
tabling / memoization to this strategy became quite complicated and the BFP is meant to address (and replace) this complexity:

> One conclusion that can be drawn fromthe BFP is that it does not make sense to hierarchically structure queries according to their generation. In contrast it makes sense to rely on a static rewriting such as the Alexander or Magic Set rewriting and process the resulting rules with a semi-naive bottom-up rule engine. -- Foundations of Rule-Based Query Answering
> BFP collects generated queries and proven facts in (n-ary) relations [...] In contrast SLD-Resolution relies on 
> hierarchical data structure that relate proven facts and generated queries to the queries they come from. 
>                                   -- Backwards Fixpoint Procedure

It provides a core method 
shown below:

```python
def MagicSetTransformation( factGraph, rules, GOALS, derivedPreds=None, strictCheck = ..., noMagic=[], defaultPredicates=None):
```

that takes as input:

- A list of derived predicates (if an empty list is provided this indicates the user wants the method to determine the 
list of derived predicates by inspecting the factGraph and update the given list in place): derivedPreds
- The fact graph that we want to ask the query against (used to find derived predicates if an empty list is given): factGraph
- A list of 3-item tuples each representing a SPARQL Basic Graph Pattern: GOALS
- A set of safe RIF-Core rules: rules
- Additional parameters described below

It re-writes the rules into a more optimal form. The rules are modified so that they only search the proof space 
relevant for the query posed by the user. For most classes of problems, when the re-written rules are evaluated will be 
evaluated just as efficiently via forward-chaining as it would via backwards chaining 
(using a Prolog-like mechanism, for instance). So, the RETE-UL network can be used to evaluate queries 
(expressed as SPARQL BGPs) via forward-propagation or using the backward chaining capabilities

The method returns a generator over the re-written rules and updates the given factGraph, adding to the adorned program 
via the .adornedProgram attribute. An adorned program is a ruleset where the literals have been adorned with information 
about how variable bindings make their way from a goal through the series of rules that are applicable and is used to 
create the re-written ruleset and also used by the backward chainer (see below).

The MagicSetTransformation method requires some input about which predicates are derived 
(it assumes the others are base predicates). For more information on this distinction, see Base and Derived Predicates. 
In addition, the method also takes a flag that takes 1 of 4 values (the strictCheck argument) determining how strictly 
to adhere to a clean separation between the two:

```python
FuXi.Rete.Magic.DDL_STRICTNESS_LOOSE
FuXi.Rete.Magic.DDL_STRICTNESS_LOOSE
FuXi.Rete.Magic.DDL_STRICTNESS_HARSH
FuXi.Rete.Magic.DDL_STRICTNESS_FALLBACK_BASE
FuXi.Rete.Magic.DDL_STRICTNESS_FALLBACK_DERIVED
```

Finally, it also takes a defaultPredicates argument that is a two item tuple where the first item is a list of 
default base predicates and the second is a list of default derived predicates. These are meant to be used with the 
last two strictness flags.

When the first flag is used, this indicates that the rule-rewriting state should not check to ensure that predicates 
are not both base and derived. The second flag indicates that an exception will be raised if any predicate is found to 
be both. The third and forth with cause a clashing predicate to be labeled as either a base or derived predicate 
respectively (i.e., the default fallback if there is a clash). This rule will be overridden by the user-provided 
list of default base and derived predicates. So, for example, if the user indicates the third flag (fallback to base) 
but a clashing predicate is in the provided list of derived predicates, it will be marked as a derived predicate.

### IdentifyDerivedPredicates ### 
A helper function which takes a DDL graph, an OWL graph (the TBox), and a ruleset and returns the set of derived predicates. See the signature of the method.

### FuXi.SPARQL ###
The implementation for a BackwardsChainingStore. A backwards chaining store can be setup this way:

```python
from FuXi.SPARQL.BackwardChainingStore import TopDownSPARQLEntailingStore 
topDownStore=TopDownSPARQLEntailingStore( factGraph.store, factGraph, set(dPreds), rules, nsBindings=nsMap, DEBUG=DEBUG) 
targetGraph = Graph(topDownStore) 
topDownStore.targetGraph = targetGraph
```

Where factGraph is an rdflib graph instance, dPreds is a set of URIs each of which is the name of a derived predicate 
in the IDB, rules is a set of clauses that comprise the IDB, and nsBindings is a namespace mapping. At this point, a 
SPARQL query can be dispatched to targetGraph (via targetGraph.query('... SPARQL ...') using derived predicates and the 
sip strategy will be used to solve the (high-level) query through a series of query re-writing which produce base 
queries (i.e., queries only involving base predicates) to evaluate against factGraph and combine such answers in order 
to answer the original query.

In this way, a (possibly large) SQL-based RDFLib backend can be queried using derived predicates defined by a domain 
theory expressed as any combination of RIF Core, N3, and/or OWL2-RL such that additional answers that follow from the 
domain theory will be provided to the query.

### FuXi.Rete.TopDown ### 
The FuXi.Rete.TopDown module has since been deprecated by the Backwards Fixpoint Procedure (BFP). See backward chaining

#### SPARQL FILTER Templates and Top Down Builtins ####
Building a ruleset with a set of defined builtin implementations (as Python functions) will provide the means to use 
builtins for forward chained inference via the RETE-UL network. However, as mentioned here the backward chaining inference 
engine can be used to as a kind of semantic query mediator to solve a SPARQL triple pattern (that uses derived predicates) 
by dispatching and combining answers from a series of intermediate SPARQL queries. Any builtins in the body (or antecedent) 
of a rule can be sent along with these queries using an RDF-based templating system that specifies how to convert a 
builtin function into a SPARQL FILTER expression.

The factGraph given to the SipStrategy method can have attached to it, a mapping from predicates to SPARQL FILTER 
expressions which are Python string templates that will be substituted with the parameters of the builtin as it is used 
to solve the original query. Given a graph such as the example in the overview, we can create and attach the mapping 
this way:

```python
factGraph.templateMap = dict([(pred,template) for pred,_ignore,template in 
                              builtinTemplateGraph.triples( (None, TEMPLATES.filterTemplate, None))])
```

Where builtinTemplateGraph is a graph of the templates. A SPARQL FILTER template builtin (N3) graph can be specified to 
the FuXi command-line via the --builtinTemplates options:

### FuXi.DLP ###

This module is a Description Horn Logic implementation as defined by Grosof, B. et.al. 
("Description Logic Programs: Combining Logic Programs with Description Logic"  @p117-grosof.pdf) in section 4.4. 
As such, it implements recursive mapping functions "T", "Th" and "Tb" which result in "custom" (dynamic) rulesets.

For the non logic-inclined, this essentially allows OWL ontologies (or a subset of OWL ontologies) to be automatically 
converted to a set of rules that exactly capture the semantics of the OWL document. This mechanism is fundamental to 
the larger framework that FuXi is a part of (python-dlp). The premise is two-fold.

First (and most importantly), the ruleset(s) generated from an OWL ontology will be much more tailored to the specific 
constraints of the ontology than a general-purpose ruleset would. As such, the inference mechanism will be several orders 
of magnitude more efficient.

Secondly, tools that are used for authoring OWL ontologies are significantly more mature than those used for authoring 
[Notation 3](https://www.w3.org/DesignIssues/Notation3.html)) rulesets (or any other comparable semantic web rule language). 
Using the DLP mechanism, a domain expert can model the semantics of a particular domain using any off-the-shelf 
OWL editor and generate a corresponding ruleset.

To invoke the DLP implementation, a developer would do the following:

```python from FuXi.Rete.Util import generateTokenSet 
from FuXi.DLP.DLNormalization import NormalFormReduction

NormalFormReduction(tBoxGraph)
network.setupDescriptionLogicProgramming(tBoxGraph)
network.feedFactsToAdd(generateTokenSet(tBoxGraph))
network.feedFactsToAdd(generateTokenSet(someRDFGraph)) 
```

The setupDescriptionLogicProgramming method can be invoked on a ReteNetwork instance, passing in an RDFLib Graph that 
consists of the OWL assertions that we wish to translate to a ruleset as the only argument. This method will return a 
list of RuleSet objects each of which represents a rule that was translated from the OWL assertions.

This method also takes a safety keyword that is any of the safety flags described above.

Note, the TBox OWL RDF graph is normalized before using the setupDescriptionLogicProgramming method. This is necessary 
in order to handle certain OWL nested axioms.

The following line then sends the OWL RDF assertions through the network. This is necessary to fully classify the OWL 
ontology. Then finally, an RDF graph of facts are sent through the network. Typically, a user will have an RDF graph 
with instance-level statements (the ABox) and an OWL RDF graph that describes the vocabulary terms used in the instance 
graph (the TBox). After following the three steps above, the network.inferredFacts graph will now have all the RDF 
statements that can be inferred from the combination of the OWL graph and the instance graph. Note, the DLP algorithm 
only supports a subset of OWL-DL, so not all OWL graphs will be properly axiomatized.

Finally, a network can be reset via the network.reset() method. This will clear the RETE-UL network, and is useful when 
you want to setup a network once from an OWL graph and calculate the closure delta graph for multiple instance graphs 
from the same ruleset. After resetting the network, the TBox graph will both need to be sent through the network again, 
followed by the later instance graph:

```python
network.setupDescriptionLogicProgramming(tBoxGraph) 
network.feedFactsToAdd(generateTokenSet(tBoxGraph)) 
network.feedFactsToAdd(generateTokenSet(someRDFGraph1)) 
network.reset() 
network.feedFactsToAdd(generateTokenSet(tBoxGraph)) 
network.feedFactsToAdd(generateTokenSet(someRDFGraph2)) ..etc..```

Or, consider the use of HornFromDL to do something similar, but more directly:

```python
from FuXi.Horn.HornRules import HornFromDL 
from rdflib.Graph import Graph 
from rdflib.util import first 
first([r for r in HornFromDL(Graph().parse('http://www.lehigh.edu/%7Ezhp2/2004/0401/univ-bench.owl')) if not r.isSafe()]) ```

```console
Forall ?X ( Exists _:tCDCSqnL314 ( Course(tCDCSqnL314) ) :- TeachingAssistant(?X) )
```

Here, the first unsafe rule from the Lehigh University Benchmark ontology is printed out. The rule is unsafe because 
the existential variable in the rule head does not appear in the body.

We can look at the OWL formulae associated with the TeachingAssistant class to see why its conversion to rules includes 
an unsafe rule:

```console
$ FuXi --class=:TeachingAssistant --output=man-owl
http://www.lehigh.edu/%7Ezhp2/2004/0401/univ-bench.owl 
... snip ... 
Class: :TeachingAssistant ## A Defined Class (university teaching assistant) ## EquivalentTo: :Person that ( :teachingAssistantOf some :Course )```
```

### FuXi.LP ### 
A backwards fixpoint procedure (BFP) implementation in Python.

A sound and complete query answering method for recursive databases based on meta-interpretation called 
Backward Fixpoint Procedure

Uses RETE-UL as the RIF PRD implementation of a meta-interpreter of an adorned ruleset that builds large, 
conjunctive (BGPs) SPARQL queries.

Uses the specialized BFP meta-interpretation rules to build a RETE-UL decision network that is modified to support the 
propagation of bindings from the evaluate predicates into a supplimental magic set sip strategy and the generation of 
subqueries. The end result is a bottom-up simulation of SLD resolution with complete, sound, and safe memoization in 
the face of recursion.

Specialization is applied to the BFP meta-interpreter with respect to the rules of the object program. For each rule of 
the meta-interpreter that includes a premise referring to a rule of the object program, one specialized version is 
created for each rule of the object program.

OpenQuery is used with predicate symbols to indicate a query without any bindings provided to the program 
(disadvantageous for GMS).

The semantics of the evaluate predicate is as follows: in each case, we add entailed evaluate bindings 
(as high-arity predicates) directly into RETE-UL beta node memories in a circular fashion, propagating their successor.

The Beta Nodes are changed in the following way:

Take a BetaNode (and a BFP rule) that joins values from an evaluate condition with other conditions and replace 
the alpha node (and memory) used to represent the condition with a pass-thru beta with no parent nodes but whose 
right memory will be used to add bindings instantiated from evaluate assertions in the BFP algorithm.
