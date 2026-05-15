==========
Quickstart
==========

FuXi (pronounced *foo-shee*) is a bi-directional semantic web reasoning
engine built on `RDFLib <https://github.com/RDFLib/rdflib>`_.
It supports **forward chaining** via a RETE-UL network (see :doc:`FuXiUserManual`)
and **backward chaining** via a Backward Fixpoint Procedure (BFP) (see :doc:`TopDownSW`),
with automatic translation of OWL ontologies into Horn rules through Description
Logic Programming (DLP) (see :doc:`FuXiSemantics`).

Architecture at a Glance
------------------------

.. mermaid::

   flowchart LR
       RDF["RDF/OWL Graphs"]
       Infix["fuxi.Syntax\n(InfixOWL)"]
       DLP["fuxi.DLP\n(OWL -> Rules)"]
       Horn["fuxi.Horn\n(Rule Model)"]
       Rete["fuxi.Rete\n(Forward Chaining)"]
       LP["fuxi.LP\n(BFP / Backward Chaining)"]
       SPARQL["fuxi.SPARQL\n(Interlocution)"]
       Stores["Local/Remote\nRDF Stores"]

       RDF --> Infix
       Infix --> DLP
       DLP --> Horn
       Horn --> Rete
       LP --> Rete
       LP --> SPARQL
       SPARQL <--> Stores

.. _quickstart-comparison:

Comparison with Other Reasoners
--------------------------------

+------------------+------------+-----------+----------------+------------------+-------------------+
| Feature          | FuXi       | OWL-RL    | ROBOT          | Pellet           | HermiT            |
+==================+============+===========+================+==================+===================+
| Language         | Python     | Python    | Java           | Java             | Java              |
+------------------+------------+-----------+----------------+------------------+-------------------+
| RDFLib native    | Yes        | Yes       | No (OWL API)   | No (OWL API)     | No (OWL API)      |
+------------------+------------+-----------+----------------+------------------+-------------------+
| OWL profile      | RL + DLP   | RL        | DL / EL / RL   | DL               | DL                |
+------------------+------------+-----------+----------------+------------------+-------------------+
| Forward chaining | RETE-UL    | Rule      | Reasoner       | Tableaux         | Tableaux          |
|                  |            | expansion | plugin         |                  |                   |
+------------------+------------+-----------+----------------+------------------+-------------------+
| Backward chaining| BFP        | No        | No             | No               | No                |
+------------------+------------+-----------+----------------+------------------+-------------------+
| SPARQL entailment| Yes        | No        | No             | Yes              | Yes               |
+------------------+------------+-----------+----------------+------------------+-------------------+
| Remote SPARQL    | Yes        | No        | No             | No               | No                |
| mediation        |            |           |                |                  |                   |
+------------------+------------+-----------+----------------+------------------+-------------------+
| OWL construction | InfixOWL   | No        | No             | No               | No                |
| DSL              |            |           |                |                  |                   |
+------------------+------------+-----------+----------------+------------------+-------------------+
| Proof generation | Yes (PML)  | No        | Explain        | Yes              | Yes               |
+------------------+------------+-----------+----------------+------------------+-------------------+
| DLP / OWL->Rules | Yes        | No        | No             | No               | No                |
+------------------+------------+-----------+----------------+------------------+-------------------+
| CLI              | Yes        | Yes       | Yes            | Yes              | Yes               |
+------------------+------------+-----------+----------------+------------------+-------------------+

FuXi's distinguishing features are its **bi-directional** reasoning
(forward and backward chaining in one system), **SPARQL 1.1 entailment
regime** support with remote endpoint mediation, and the **InfixOWL**
Pythonic DSL for constructing OWL ontologies programmatically.

- **`OWL-RL <https://github.com/RDFLib/OWL-RL>`_**: A forward-chaining-only
  OWL 2 RL implementation on RDFLib. Simpler API but no backward chaining,
  no SPARQL entailment regimes, and no OWL construction DSL.

- **`ROBOT <https://robot.obolibrary.org/>`_**: A Java-based ontology
  toolkit focused on OBO workflows. Provides reasoning via external
  reasoners (ELK, HermiT, etc.) but is not Python-native and does not
  support SPARQL entailment or bi-directional reasoning.

Installation
------------

.. code-block:: bash

   uv venv
   source .venv/bin/activate
   uv pip install -e .

See :doc:`Installation_Testing` for additional setup details and
:doc:`Overview` for the full architecture description.

Command-Line Quick Reference
----------------------------

FuXi includes focused CLI sub-commands:

- ``fuxi.core`` for forward chaining and RETE diagnostics
- ``fuxi.proof`` for BFP query answering and proof/SIP graph outputs
- ``fuxi.owl`` for OWL/DLP workflows and Manchester OWL output

The legacy ``fuxi`` command remains available as a compatibility wrapper.

.. code-block:: bash

   uv run --active --extra dev fuxi.core [options] factFile1 factFile2 ...
   uv run --active --extra dev fuxi.proof [options] factFile1 factFile2 ...
   uv run --active --extra dev fuxi.owl [options] factFile1 factFile2 ...

Most-used options:

- ``--rules PATH_OR_URI`` (repeatable): N3 rulesets
- ``--input-format {xml,trix,n3,nt,rdfa}``: RDF input format
- ``--output FORMAT``: select serialization or graph output mode
- ``--why "SPARQL query"``: top-down query goal (``fuxi.proof`` or ``fuxi.owl``)
- ``--method {naive,bfp}``: reasoning mode (``fuxi.owl`` and compatibility wrapper)

.. _quickstart-sparql-entailment:

SPARQL Entailment Test Harness
------------------------------

FuXi ships a manifest-driven SPARQL entailment regression harness:

.. code-block:: bash

   uv run pytest test/SPARQL/test_sparql_entailment.py

Useful focused runs:

.. code-block:: bash

   # run one manifest test ID
   uv run pytest test/SPARQL/test_sparql_entailment.py --single-test rdfs04

   # run a subset by pytest expression
   uv run pytest test/SPARQL/test_sparql_entailment.py -k "paper-sparqldl-Q1-rdfs or sparqldl-05"

Harness behavior summary:

- Collects one pytest case per approved W3C manifest entry.
- Runs currently supported regimes (RDFS/RDF) through
  ``owl_entailment_regime_graph``.
- For ASK queries, compares expected and actual booleans exactly.
- For SELECT-style result sets, requires expected bindings to be present;
  additional inferred bindings are tolerated.
- Uses explicit skip marks for known unsupported areas (for example,
  BIND-heavy algebra and OWL-strength SPARQL-DL cases outside current
  RDFS/RDF scope).

Notable output modes:

- ``n3``, ``nt``, ``xml``, ``TriX``: RDF output
- ``proof-graph-svg`` / ``proof-graph-png``: BFP proof graph
- ``rete-network-svg`` / ``rete-network-png``: RETE network graph
- ``sip-collection-svg`` / ``sip-collection-png``: SIP graph

Graph outputs are written directly to stdout; redirect them to files:

.. code-block:: bash

   uv run --active --extra dev fuxi.proof \
      --rules test/command_line_test_rules.n3 \
      --input-format n3 \
      --ns fam=http://dev.w3.org/2000/10/swap/test/cwm/fam.n3# \
      --why "PREFIX fam: <http://dev.w3.org/2000/10/swap/test/cwm/fam.n3#> SELECT ?a { fam:david fam:ancestor ?a }" \
      --output proof-graph-svg \
      test/command_line_facts.n3 > proof.svg

.. note::

   ``proof-graph-*`` and ``sip-collection-*`` require ``--why --method=bfp``.
   Graph rendering requires Graphviz (``dot`` binary) installed.

Example 1: Forward Chaining with N3 Rules
-------------------------------------------

Build a RETE-UL network from Notation 3 rules, feed it facts, and
collect inferred triples:

.. code-block:: python

   from fuxi.Rete.RuleStore import setup_rule_store
   from rdflib import Graph, Namespace

   ex = Namespace("http://example.org/")

   rules_n3 = """
       @prefix ex: <http://example.org/> .
       { ?s ex:parent ?o } => { ?o ex:child ?s } .
   """

   rule_store, rule_graph, network = setup_rule_store(rules_n3, make_network=True)

   facts = Graph()
   facts.parse(data="""
       @prefix ex: <http://example.org/> .
       ex:Alice ex:parent ex:Bob .
   """, format="turtle")

   network.feed_facts_to_add(facts)

   for s, p, o in network.inferred_facts:
       print(s, p, o)
   # ex:Bob ex:child ex:Alice

The RETE-UL network efficiently matches rule antecedents against
working-memory elements (RDF triples).  When all conditions in a rule
are satisfied, the consequent fires and the inferred triple is added to
``network.inferred_facts``.  See :doc:`FuXiUserManual` for details on
network construction, built-in predicates, and conflict-set reporting.

RETE Network Flow
~~~~~~~~~~~~~~~~~

.. mermaid::

   flowchart LR
       Facts["Input Facts (WMEs)"] --> Alpha["Alpha Nodes\n(pattern match)"]
       Alpha -->|tokens| Beta["Beta Nodes\n(joins)"]
       Beta -->|partial match tokens| Terminal["Terminal Nodes\n(rule fired)"]
       Terminal -->|assert inferred triples| WM["Working Memory / Inferred Graph"]
       WM -->|new facts| Alpha

Example 2: OWL to Rules via DLP
--------------------------------

Convert an OWL ontology into Horn rules and use them for inference:

.. code-block:: python

   from fuxi.Rete.RuleStore import setup_rule_store
   from rdflib import Graph

   owl_graph = Graph()
   owl_graph.parse("http://www.lehigh.edu/~zhp2/2004/0401/univ-bench.owl")

   rule_store, rule_graph, network = setup_rule_store(make_network=True)

   dlp_rules = network.setup_description_logic_programming(
       owl_graph,
       safety="none",
   )

   facts = Graph()
   facts.parse(data=some_instance_data, format="turtle")
   network.feed_facts_to_add(facts)

   for s, p, o in network.inferred_facts:
       print(s, p, o)

The DLP transformation implements the T, Th, and Tb mapping functions
from Grosof et al., converting a subset of OWL-DL axioms into definite
Horn rules that exactly capture the ontology's semantics.  Only the
DLP-intersectable fragment of OWL is supported.  See :doc:`FuXiSemantics`
for normal-form reductions and :doc:`Overview` for the full DLP theory.

Example 3: Building OWL Ontologies with InfixOWL
--------------------------------------------------

InfixOWL provides a Pythonic DSL for constructing OWL class expressions
using infix operators (``&``, ``|``, ``~``) and Pythonic property
comparisons:

.. code-block:: python

   from rdflib import Graph, Literal, Namespace, XSD
   from fuxi.Syntax.InfixOWL import Class, Property, Restriction

   ex = Namespace("http://example.org/")
   g = Graph()

   Person = Class(ex.Person, graph=g)
   Parent = Class(ex.Parent, graph=g)
   hasChild = Property(ex.hasChild, graph=g)

   # Equivalent class: Parent ≡ Person ⊓ ∃hasChild.Person
   Parent.equivalent_class = [
       Person & Restriction(hasChild, some_values_from=Person)
   ]

   print(g.serialize(format="turtle"))

InfixOWL operators at a glance:

+--------------------------------------+---------------------------------------------+
| Expression                           | InfixOWL                                    |
+======================================+=============================================+
| Intersection (A ⊓ B)                 | ``A & B``                                   |
+--------------------------------------+---------------------------------------------+
| Union (A ⊔ B)                        | ``A | B``                                   |
+--------------------------------------+---------------------------------------------+
| Complement (¬A)                      | ``~A``                                      |
+--------------------------------------+---------------------------------------------+
| ∃p.C (someValuesFrom)                | ``Restriction(p, some_values_from=C)``      |
|                                      | or ``p.some(C)``                            |
+--------------------------------------+---------------------------------------------+
| ∀p.C (allValuesFrom)                 | ``Restriction(p, all_values_from=C)``       |
|                                      | or ``p.only(C)``                            |
+--------------------------------------+---------------------------------------------+
| ≥ n p (minCardinality)               | ``p.cardinality >= n``                      |
+--------------------------------------+---------------------------------------------+
| ≤ n p (maxCardinality)               | ``p.cardinality <= n``                      |
+--------------------------------------+---------------------------------------------+
| = n p (exactCardinality)             | ``p.cardinality == n``                      |
+--------------------------------------+---------------------------------------------+
| ≥ n p.C (minQualifiedCardinality)    | ``p.cardinality(C) >= n``                   |
+--------------------------------------+---------------------------------------------+
| ≤ n p.C (maxQualifiedCardinality)    | ``p.cardinality(C) <= n``                   |
+--------------------------------------+---------------------------------------------+

See :doc:`InfixOwl` for the full InfixOWL documentation.

Example 4: Backward Chaining with SPARQL Entailment
----------------------------------------------------

Query derived predicates without materializing all inferences, using the
Backward Fixpoint Procedure (BFP):

.. code-block:: python

   from io import StringIO

   from rdflib import Graph, Namespace, RDF

   from fuxi.Horn.HornRules import horn_from_n3
   from fuxi.SPARQL.utilities import owl_entailment_regime_graph

   ex = Namespace("http://example.org/")
   fact_graph = Graph().parse("path/to/facts.ttl", format="turtle")
   ns_map = {"ex": ex}

   rules_n3 = """
       @prefix ex: <http://example.org/> .
       { ?s ex:parentOf ?o } => { ?s ex:relatedTo ?o } .
   """
   extra_rulesets = [horn_from_n3(StringIO(rules_n3))]

   goals = [
       (ex.alice, RDF.type, ex.Person),
       (ex.alice, ex.parentOf, ex.bob),
   ]

   entail_graph, _closure_delta = owl_entailment_regime_graph(
       fact_graph,
       ns_map,
       extra_rulesets=extra_rulesets,
       goals=goals,
   )

   result = entail_graph.query(
       "SELECT ?s ?o WHERE { ?s ex:relatedTo ?o }"
   )

The BFP uses RETE-UL as a meta-interpreter over an adorned program,
building conjunctive SPARQL queries against the fact graph.  This avoids
full materialization and works with both local and remote data sources.
See :doc:`TopDownSW` for the full top-down query mediation walkthrough
and :doc:`data_description_language` for how to declare EDB/IDB
predicates that control the BFP adornment and magic-set rewriting.

BFP / Magic Set Flow
~~~~~~~~~~~~~~~~~~~~~

.. mermaid::

   flowchart LR
       Goal["Goal Triple Patterns"] --> Adorn["Adornment\n(bound/free analysis)"]
       Adorn --> Magic["Magic Predicates\n(seed facts)"]
       Magic --> Rewrite["Rewrite Rules\n(adorned + magic rules)"]
       Rewrite --> SIP["SIP Graph\n(binding propagation)"]
       SIP --> Eval["Bottom-up Evaluation\n(RETE over EDB)"]
       Eval --> Answers["Derived Answers"]

Example 5: Querying a Remote SPARQL Endpoint
----------------------------------------------

FuXi can mediate SPARQL queries against remote endpoints, combining
local rules with remote data:

.. code-block:: python

   from rdflib import Variable
   from fuxi.SPARQL.service import sparql_interlocution

   for answer in sparql_interlocution(query, top_down_store):
       movie = answer[Variable('movie')]
       print(f"Movie: {movie}")

The ``TopDownSPARQLEntailingStore`` partitions triple patterns into EDB
(base) and IDB (derived) predicates, dispatching EDB patterns as SPARQL
queries to the remote endpoint while evaluating IDB patterns via BFP.
See :doc:`TopDownSW` for the SPARQL interlocution architecture and
:doc:`data_description_language` for DDL configuration of EDB/IDB
predicate classification.

Choosing a Strategy
-------------------

=====================================  =====================================
Use **forward chaining** when          Use **backward chaining** when
=====================================  =====================================
You need all inferred triples          You need answers to specific queries
Small-to-medium datasets               Large or remote datasets
One-time batch processing              Interactive / on-demand queries
OWL DLP closure calculation            SPARQL 1.1 entailment regimes
=====================================  =====================================

Next Steps
----------

- :doc:`Overview` — full architecture, design principles, and component relationships
- :doc:`FuXiUserManual` — detailed RETE network setup, DLP usage, and built-in predicates
- :doc:`InfixOwl` — InfixOWL API reference for OWL class/property construction
- :doc:`TopDownSW` — top-down SPARQL query mediation and BFP internals
- :doc:`data_description_language` — DDL vocabulary for EDB/IDB partitioning
- :doc:`FuXiSemantics` — OWL/RIF semantics, normal forms, and negation handling
- :doc:`builtin_SPARQL_templates` — SPARQL FILTER templates for N3 built-ins
- :doc:`ReteActions` — RETE network action hooks and custom consequents
- :doc:`Tutorial` — step-by-step tutorial with larger examples
