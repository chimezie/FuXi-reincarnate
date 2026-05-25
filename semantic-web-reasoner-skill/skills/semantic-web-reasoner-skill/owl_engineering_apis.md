```python
from fuxi.Syntax.InfixOWL import GraphContext, Class, Property, AnnotationProperty
from rdflib import Graph, Namespace, Literal

g = Graph()
NS = {"ex": "http://example.org/"}
with GraphContext(g, NS):
    person = Class(NS.ex.Person, label="Person")
    has_child = Property(NS.ex.hasChild, domain=[person])
    parent = Class(NS.ex.Parent)
    parent.equivalent_class = [person & has_child.some(person)]
```

To add annotation to an ontology:

```python
from fuxi.Syntax.InfixOWL import Class, Property, GraphContext
from rdflib import Graph, Namespace, Literal
g = Graph()

IMDB = Namespace("https://www.imdb.com/")
MY_NS = Namespace("tag:info@metacognition.info,2026:FuXiSPARQLExample#")
OWL_DSL = Namespace("https://github.com/chimezie/OWL_DSL/tree/main/ontology_configurations/")

with GraphContext(g, {"my": MY_NS, "owl_dsl": OWL_DSL, "imdb": IMDB}):
    movie = Class(IMDB.Movie, label=Literal("Movie"))
    person = Class(MY_NS.Person, label=Literal("Person"))
    singular_annotation = OWL_DSL.OWL_DSL_000001 #singular predicate string template
    film_director = Property(MY_NS.film_director, domain=[movie], range=[person])
    film_director.set_annotation(singular_annotation, "directed by {}")

print(g.serialize(format="ttl"))
```