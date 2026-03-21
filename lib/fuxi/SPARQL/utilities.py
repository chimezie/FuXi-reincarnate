from typing import List, Union, Dict, Tuple, Optional
from rdflib.plugins.sparql.parserutils import CompValue
from pyparsing import ParseResults
from rdflib import URIRef
from rdflib.query import Result
from rdflib.plugins.sparql.processor import SPARQLResult

def sparql_query_from_result(result: Result) -> SPARQLResult:
    mapping = {
        "type_": result.type,
        "vars_": result.vars,
        "bindings": result.bindings,
        "askAnswer": result.askAnswer,
        "graph": result.graph,
    }
    return SPARQLResult(mapping)

def extract_list_from_comp_values(query_structure: CompValue,
                                  field: str) -> List[Union[ParseResults, CompValue, List[CompValue]]]:
    items = query_structure[field]
    assert isinstance(items, list)
    for component in items:
        if isinstance(component, ParseResults):
            yield list(component)
        elif isinstance(component, CompValue):
            yield component
        else:
            raise Exception(f"Unknown type: {type(component)}")


def extract_triples_from_triple_part(triple_part: CompValue,
                                     nsBinds: Dict[str, URIRef]) -> Tuple[URIRef, URIRef, URIRef]:
    if triple_part.name == 'pname':
        return URIRef(nsBinds[triple_part.prefix] + triple_part.localname)
    elif triple_part.name == 'PathAlternative':
        return extract_triples_from_triple_part(triple_part.part[0].part[0].part, nsBinds)
    else:
        raise Exception(f"Unknown type: {type(triple_part)}")


def extract_triples_from_query(query_structure: CompValue,
                               nsBinds: Dict[str, URIRef],
                               triples: Optional[List] = None) -> List[Tuple[URIRef, URIRef, URIRef]]:
    triples = triples if triples is not None else []
    if query_structure.name == 'AskQuery':
        component = query_structure['where']
        assert isinstance(component, CompValue)
        extract_triples_from_query(component, nsBinds, triples)
    elif query_structure.name in ['GroupGraphPatternSub']:
        for component in extract_list_from_comp_values(query_structure, 'part'):
            extract_triples_from_query(component, nsBinds, triples)
    elif query_structure.name in 'TriplesBlock':
        for item in extract_list_from_comp_values(query_structure, 'triples'):
            if isinstance(item, list) and len(item) == 3:
                triples.append(tuple(map(lambda i: extract_triples_from_triple_part(i, nsBinds), item)))
            else:
                raise Exception(f"Unknown type: {type(item)}")
    elif query_structure.name == 'BGP':
        triples.extend(query_structure.triples)
    elif query_structure.name == 'SelectQuery':
        extract_triples_from_query(query_structure.p, nsBinds, triples)
    elif query_structure.name == 'Project':
        extract_triples_from_query(query_structure.p, nsBinds, triples)
    else:
        raise Exception(f"Unknown type: {type(query_structure)}")
    return triples
