import { Plugin } from "@opencode-ai/plugin"
import checkOntology from "./check-ontology.js"
import classEntailments from "./class-entailments.js"
import createOntology from "./create-ontology.js"
import dirOntology from "./dir-ontology.js"
import extractClass from "./extract-class.js"
import findOntologyClass from "./find-ontology-class.js"
import findOntologyProperty from "./find-ontology-property.js"
import listOntologies from "./list-ontologies.js"
import ontologyMeasureEssentials from "./ontology-measure-essentials.js"
import ontologyReport from "./ontology-report.js"
import setAltLabel from "./set-alt-label.js"
import setAnnotation from "./set-annotation.js"
import setEditorialNote from "./set-editorial-note.js"
import setHumanReadableDefinition from "./set-human-readable-definition.js"
import setLabel from "./set-label.js"
import sparqlInterlocution from "./sparql-interlocution.js"
import verbalizeOntologyClass from "./verbalize-ontology-class.js"

const MySkillPlugin: Plugin = async () => {
  return {
    tool: {
      "check-ontology": checkOntology,
      "class-entailments": classEntailments,
      "create-ontology": createOntology,
      "dir-ontology": dirOntology,
      "extract-class": extractClass,
      "find-ontology-class": findOntologyClass,
      "find-ontology-property": findOntologyProperty,
      "list-ontologies": listOntologies,
      "ontology-measure-essentials": ontologyMeasureEssentials,
      "ontology-report": ontologyReport,
      "set-alt-label": setAltLabel,
      "set-annotation": setAnnotation,
      "set-editorial-note": setEditorialNote,
      "set-human-readable-definition": setHumanReadableDefinition,
      "set-label": setLabel,
      "sparql-interlocution": sparqlInterlocution,
      "verbalize-ontology-class": verbalizeOntologyClass,
    },
  }
}

export default MySkillPlugin