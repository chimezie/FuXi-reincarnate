class Node:

    """
    A node in a Rete network.  Behavior between Alpha and Beta (Join) nodes
    """
    def __init__(self):
        self.descendent_memory = []
        self.descendent_beta_nodes = set()

    def update_descendent_memory(self, memory):
        if memory.successor not in [
                mem.successor for mem in self.descendent_memory]:
            self.descendent_memory.append(memory)

    def connect_to_beta_node(self, beta_node, position):
        self.update_descendent_memory(beta_node.memories[position])
        self.descendent_beta_nodes.add(beta_node)
