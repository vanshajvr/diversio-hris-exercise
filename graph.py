"""
Here the basic logic is computing roots, manager leading us to 
direct-report counts, and reporting cycles.
each employee has atmost one manager, so reporting structure is a "functional graph"
(because out-degree <= 1 per node), it lets cycle detection in O(n) total.
each node here is visited atmost once across all traversals, using a state map
instead of per-node recursion.

"""


from models import Employee

def compute_roots(employees:list[Employee])->list[Employee]:
    
    #A root is an employee who supplied neither manager field in the source data
    #but distinct from someone whose manager reference failed to resolve.

    return [e for e in employees if not e.manager_id and not e.manager_email]

def compute_manager_counts(employees:list[Employee])->dict:
    counts:dict={}
    for e in employees:
        if e.resolved_manager_id:
            counts[e.resolved_manager_id]=counts.get(e.resolved_manager_id,0)+1
    return counts

def find_cyclic_employees(employees:list[Employee])->set:
    manager_of={e.employee_id:e.resolved_manager_id for e in employees if e.resolved_manager_id}
    state: dict={} #employee_id -> "visiting" | "done"
    cyclic: set=set()

    for start_id in manager_of:
        if state.get(start_id)=="done":
            continue

        path=[]
        node=start_id
        while True:
            if state.get(node)=="done":
                break #previously proven to lead into a cycle
            if state.get(node)=="visiting":
                #back-edge found:
                #everyone from node's first occurence in this path onward is part of cycle
                idx=path.index(node)
                cyclic.update(path[idx:])
                break
            if node not in manager_of:
                break #chain ends at a root or an unresolved manager

            state[node]="visiting"
            path.append(node)
            node=manager_of[node]

        for n in path:
            if state.get(n)=="visiting":
                state[n]="done"

    return cyclic