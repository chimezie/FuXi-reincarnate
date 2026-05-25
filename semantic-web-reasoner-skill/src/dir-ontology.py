
# /// script
# requires-python = ">=3.11"
# dependencies = ["owlready2"]
# ///
"""
dir-ontology.py — List the terms in an ontology as Manchester OWL

Positional arguments:
- SQLite file (sqlite_file): Path to SQLite file with pre-loaded ontology
"""
import sys

from owlready2 import (
    And,
    Inverse,
    Not,
    OneOf,
    Or,
    Restriction,
    ThingClass,
    default_world,
    get_ontology,
)


def _name(e):
    """Get a clean name for an OWL entity."""
    if e is None:
        return ''
    if isinstance(e, str):
        return e
    if hasattr(e, 'name'):
        return e.name.split('.')[-1]
    return str(e)


def _render_restriction(sup):
    """Render a Restriction object in Manchester OWL fragment."""
    pname = _name(sup.property)
    t = getattr(sup, 'type', None)
    v = getattr(sup, 'value', None)

    if t is None and v is None:
        return repr(sup)

    graph = default_world.graph
    svf = graph.execute(
        "SELECT storid FROM resources WHERE iri=?",
        ('http://www.w3.org/2002/07/owl#someValuesFrom',)
    ).fetchone()
    hv = graph.execute(
        "SELECT storid FROM resources WHERE iri=?",
        ('http://www.w3.org/2002/07/owl#hasValue',)
    ).fetchone()
    svf_storid = svf[0] if svf else None
    hv_storid = hv[0] if hv else None

    if svf_storid is not None and t == svf_storid:
        if isinstance(v, ThingClass):
            return f"({pname} some {_name(v)})"
        elif isinstance(v, type):
            dtype = 'integer' if v is int else 'string' if v is str else str(v)
            return f"({pname} some {dtype})"
    elif hv_storid is not None and t == hv_storid:
        return f"({pname} value {_name(v)})"
    else:
        return repr(sup)


def _render_expr(expr):
    """Render an OWL expression in Manchester OWL syntax."""
    if isinstance(expr, ThingClass):
        return _name(expr)

    if isinstance(expr, Restriction):
        return _render_restriction(expr)

    if isinstance(expr, And):
        parts = []
        for c in expr.Classes:
            child = _render_expr(c)
            parts.append(f"({child})" if isinstance(c, (Or, And)) else child)
        return ' and '.join(parts)

    if isinstance(expr, Or):
        parts = []
        for c in expr.Classes:
            child = _render_expr(c)
            parts.append(f"({child})" if isinstance(c, (Or, And)) else child)
        return ' or '.join(parts)

    if isinstance(expr, Not):
        inner = _render_expr(expr.Class)
        return f"not ({inner})"

    if isinstance(expr, OneOf):
        items = ', '.join(_name(e) for e in expr.instances)
        return f"{{{items}}}"

    if isinstance(expr, Inverse):
        return f"inverse {_name(expr.property)}"

    return repr(expr)


default_world.set_backend(filename=sys.argv[1])

onto = None
for iri in default_world.ontologies:
    if iri != 'http://anonymous/':
        onto = get_ontology(iri)
        onto.load()
        break

if onto is None:
    print("No ontology found in SQLite file")
    sys.exit(1)

base = onto.base_iri if onto.base_iri else str(onto)
print(f"Ontology: {base}\n")

for cls in onto.classes():
    if cls.iri in ('http://www.w3.org/2002/07/owl#Thing',
                   'http://www.w3.org/2002/07/owl#Nothing'):
        continue
    print(f"Class: {cls.name}")

    if cls.label:
        print(f"  Annotations: rdfs:label \"{', '.join(cls.label)}\"")

    for sup in cls.is_a:
        if isinstance(sup, ThingClass):
            if sup.name not in ('Thing', 'Nothing'):
                print(f"  SubClassOf: {_name(sup)}")
        else:
            print(f"  SubClassOf: {_render_expr(sup)}")

    eq_to = cls.equivalent_to
    if eq_to:
        for eq in eq_to:
            print(f"  EquivalentTo: {_render_expr(eq)}")

    print()

# Find all properties by scanning the SQLite database directly.
# owlready2's property listing methods miss properties declared
# with OWL subclass types (e.g. SymmetricProperty without explicit
# ObjectProperty rdf:type).
graph = default_world.graph
rdf_type_s = graph.execute(
    "SELECT storid FROM resources WHERE iri=?",
    ('http://www.w3.org/1999/02/22-rdf-syntax-ns#type',)
).fetchone()[0]

prop_types_iris = [
    'http://www.w3.org/2002/07/owl#ObjectProperty',
    'http://www.w3.org/2002/07/owl#DatatypeProperty',
    'http://www.w3.org/2002/07/owl#AnnotationProperty',
    'http://www.w3.org/2002/07/owl#SymmetricProperty',
    'http://www.w3.org/2002/07/owl#FunctionalProperty',
    'http://www.w3.org/2002/07/owl#TransitiveProperty',
    'http://www.w3.org/2002/07/owl#ReflexiveProperty',
    'http://www.w3.org/2002/07/owl#IrreflexiveProperty',
    'http://www.w3.org/2002/07/owl#AsymmetricProperty',
    'http://www.w3.org/2002/07/owl#InverseFunctionalProperty',
]
prop_type_storids = []
for pt in prop_types_iris:
    row = graph.execute(
        "SELECT storid FROM resources WHERE iri=?", (pt,)
    ).fetchone()
    if row:
        prop_type_storids.append(row[0])

placeholders = ','.join('?' for _ in prop_type_storids)
rows = graph.execute(f'''
    SELECT DISTINCT r.storid, r.iri FROM resources r
    JOIN objs t ON r.storid = t.s
    WHERE t.p = ? AND t.o IN ({placeholders})
''', [rdf_type_s] + prop_type_storids)

property_storids = []
for storid, iri in rows:
    if storid not in property_storids:
        property_storids.append(storid)

# SubPropertyOf names to suppress (OWL/RDF builtins)
suppress_subprop = {
    'ObjectProperty', 'DataProperty', 'AnnotationProperty',
    'FunctionalProperty', 'SymmetricProperty', 'TransitiveProperty',
    'ReflexiveProperty', 'IrreflexiveProperty', 'AsymmetricProperty',
    'InverseFunctionalProperty', 'Property', 'DatatypeProperty',
}

for storid in property_storids:
    entity = default_world._get_by_storid(storid)
    if entity is None:
        continue
    type_name = type(entity).__name__

    print(f"Property: {entity.name}")
    if entity.label:
        print(f"  Annotations: rdfs:label \"{', '.join(entity.label)}\"")

    if type_name == 'ObjectPropertyClass':
        ptype = "ObjectProperty"
    elif type_name == 'DataPropertyClass':
        ptype = "DataProperty"
    elif type_name == 'AnnotationPropertyClass':
        ptype = "AnnotationProperty"
    else:
        ptype = "Property"
    print(f"  Type: {ptype}")

    if entity.domain:
        for d in entity.domain:
            dn = d.name if hasattr(d, 'name') else str(d)
            print(f"  Domain: {dn}")
    if entity.range:
        for r in entity.range:
            rn = r.name if hasattr(r, 'name') else str(r)
            print(f"  Range: {rn}")
    if entity.is_a:
        for sup in entity.is_a:
            sup_name = sup.name if hasattr(sup, 'name') else str(sup)
            if sup_name not in suppress_subprop:
                print(f"  SubPropertyOf: {sup_name}")
    print()
