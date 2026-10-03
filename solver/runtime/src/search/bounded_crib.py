"""Research-only standard M4 search over an explicit finite mechanical domain.

No events, statistical pruning, network, or implicit keyspace assumptions.
Budgets yield UNKNOWN; receipts certify only the supplied domain and crib.
"""
from dataclasses import replace, asdict
from hashlib import sha256
import json
from search.c3_models import Key, stream, solve_board, pair_strings, normalize, letters, step, core

VERSION = 'bounded_crib_v1'


def crib_rows(key, offset, length):
    """Event-free unplugged rows only where constraints need them.

    Advance every prefix step, including double steps; skip only electrical
    permutations outside the crib. Full candidate replay remains independent.
    """
    p=list(letters(key.positions));rings=letters(key.rings)
    for _ in range(offset):step(p,key.moving_rotors)
    rows=[]
    for _ in range(length):
        step(p,key.moving_rotors)
        rows.append(tuple(core(x,key,p,rings) for x in range(26)))
    return tuple(rows)

def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def observations(ciphertext, model='clean', index=None):
    if not ciphertext or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in ciphertext):
        raise ValueError('Explicit uppercase ciphertext required')
    values = [ord(c)-65 for c in ciphertext]
    if model == 'clean':
        if index is not None: raise ValueError('Clean model has no error index')
    elif model == 'substitution':
        if type(index) is not int or not 0 <= index < len(values): raise ValueError('Bad substitution index')
        values[index] = None
    elif model == 'omission':
        if type(index) is not int or not 0 <= index <= len(values): raise ValueError('Bad omission index')
        values.insert(index, None)  # A lost letter still consumes a machine step.
    else: raise ValueError('Unsupported model')
    return values

def completions(partial, pairs, limit):
    """Enumerate physical involutions with exactly pairs cables, without pruning."""
    result = []; truncated = False
    def visit(p):
        nonlocal truncated
        if truncated: return
        used = sum(i < x for i, x in enumerate(p))
        free = [i for i,x in enumerate(p) if x == -1]
        if used > pairs or used + len(free)//2 < pairs: return
        if not free:
            if used == pairs:
                if len(result) >= limit: truncated = True
                else: result.append(tuple(p))
            return
        a = free[0]
        q = p.copy(); q[a] = a; visit(q)
        if used < pairs:
            for b in free[1:]:
                q = p.copy(); q[a] = b; q[b] = a; visit(q)
                if truncated: break
    visit(list(partial))
    return result, truncated

def search(ciphertext, crib, offset, cores, *, model='clean', index=None,
           pairs=10, node_limit=20000, board_limit=64, completion_limit=256,
           candidate_limit=256, checkpoint=None):
    if any(type(v) is not int or v < 1 for v in (node_limit,board_limit,completion_limit,candidate_limit)):
        raise ValueError('Positive integer budgets required')
    if type(pairs) is not int or not 0 <= pairs <= 13: raise ValueError('Invalid cable count')
    obs = observations(ciphertext, model, index)
    if not crib or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in crib): raise ValueError('Invalid crib')
    if type(offset) is not int or offset < 0 or offset+len(crib) > len(obs): raise ValueError('Invalid crib offset')
    # Input has mechanical cores only: never accept a hidden plugboard oracle.
    canonical = {}
    for core in cores:
        if core.plugboard: raise ValueError('Search cores must not supply plugboard')
        k = normalize(core); canonical[digest(asdict(k))] = k
    if not canonical: raise ValueError('Explicit nonempty domain required')
    scope = dict(engine=VERSION, ciphertext=ciphertext, crib=crib, offset=offset,
        model=model,index=index,pairs=pairs,cores=[asdict(canonical[h]) for h in sorted(canonical)])
    edges = [(offset+j,ord(p)-65,obs[offset+j]) for j,p in enumerate(crib) if obs[offset+j] is not None]
    candidates=[]; unknown=0; nodes=0; visited=0
    conflict=any(a==b for _,a,b in edges)
    if not conflict:
        for h in sorted(canonical):
            if checkpoint is not None:checkpoint(visited,len(canonical))
            k=canonical[h]; visited+=1
            rows=crib_rows(k,offset,len(crib))
            local_edges=[(i-offset,a,b) for i,a,b in edges]
            solved=solve_board(rows,local_edges,max_pairs=pairs,node_limit=node_limit,solution_limit=board_limit)
            nodes+=solved['nodes']
            uncertain=solved['status']=='unknown_budget'
            for partial in solved['partial_boards']:
                boards, cut=completions(partial,pairs,completion_limit); uncertain |= cut
                for board in boards:
                    key=replace(k,plugboard=pair_strings(board))
                    # Replay all observed characters, leaving unknown plaintext explicit.
                    fullrows=stream(key,len(obs))
                    plain=''.join('?' if c is None else chr(65+fullrows[i][c]) for i,c in enumerate(obs))
                    if any(obs[offset+j] is not None and plain[offset+j]!=p for j,p in enumerate(crib)):
                        raise AssertionError('Constraint/replay disagreement')
                    if len(candidates)>=candidate_limit:
                        uncertain=True; break
                    candidates.append(dict(key=asdict(key), plaintext=plain,
                        unknown_slots=[i for i,c in enumerate(obs) if c is None]))
                if len(candidates)>=candidate_limit:
                    uncertain=True
                    break
            unknown+=int(uncertain)
            if len(candidates)>=candidate_limit:
                # Unvisited cores must never turn into a negative certificate.
                break
    complete=unknown==0 and (conflict or visited==len(canonical))
    if checkpoint is not None:checkpoint(visited,len(canonical))
    return dict(engine=VERSION,scope_hash=digest(scope),cipher_sha256=sha256(ciphertext.encode()).hexdigest(),
        status='complete_candidates' if complete and candidates else ('complete_negative' if complete else 'unknown_budget'),
        complete=complete, historical_solution=False, core_count=len(canonical), visited_cores=visited,
        nodes=nodes, candidates=candidates,
        budgets=dict(nodes_per_core=node_limit,boards_per_core=board_limit,completions_per_board=completion_limit,candidates=candidate_limit),
        model=model,index=index,crib=crib,offset=offset,pairs=pairs)
