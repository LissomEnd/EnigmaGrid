package org.enigmagrid.core;

import java.util.*;
import java.util.function.BooleanSupplier;

/** Deterministic fixed-core CSP. Cancellation never produces a negative certificate. */
public final class BoardSolver {
    public static final class Result {
        public final String status;
        public final int nodes;
        public final List<int[]> partialBoards;
        Result(String status, int nodes, List<int[]> boards) {
            this.status=status; this.nodes=nodes;
            this.partialBoards=Collections.unmodifiableList(boards);
        }
    }
    private final int[][] rows, edges;
    private final int maxPairs, nodeLimit, solutionLimit;
    private final BooleanSupplier cancelled;
    private final Set<String> seen=new HashSet<>();
    private final List<int[]> answers=new ArrayList<>();
    private int nodes;
    private boolean cutoff, stopped;
    private BoardSolver(int[][] rows,int[][] edges,int maxPairs,int nodeLimit,int solutionLimit,BooleanSupplier cancelled) {
        this.rows=rows;this.edges=edges;this.maxPairs=maxPairs;
        this.nodeLimit=nodeLimit;this.solutionLimit=solutionLimit;this.cancelled=cancelled;
    }
    public static Result solve(int[][] rows,int[][] edges,int maxPairs,int nodeLimit,int solutionLimit,BooleanSupplier cancelled) {
        if(maxPairs<0 || maxPairs>13 || nodeLimit<1 || solutionLimit<1) throw new IllegalArgumentException("Invalid budget");
        for(int[] row:rows) {
            if(row.length!=26) throw new IllegalArgumentException("Row length");
            for(int i=0;i<26;i++) if(row[i]<0 || row[i]>=26 || row[row[i]]!=i) throw new IllegalArgumentException("Non-involutive row");
        }
        for(int[] edge:edges) if(edge.length!=3 || edge[0]<0 || edge[0]>=rows.length || edge[1]<0 || edge[1]>=26 || edge[2]<0 || edge[2]>=26) throw new IllegalArgumentException("Invalid edge");
        BoardSolver s=new BoardSolver(rows,edges,maxPairs,nodeLimit,solutionLimit,cancelled);
        int[] empty=new int[26];Arrays.fill(empty,-1);s.search(empty,0);
        return new Result(s.stopped ? "cancelled" : s.cutoff ? "unknown_budget" : s.answers.isEmpty() ? "unsatisfiable" : "satisfiable",s.nodes,s.answers);
    }
    private static final class State {
        final int[] board;final int used;
        State(int[] board,int used){this.board=board;this.used=used;}
    }
    private State extend(int[] p,int used,int a,int b) {
        if((p[a]!=-1 && p[a]!=b)||(p[b]!=-1 && p[b]!=a))return null;
        if(p[a]==b)return new State(p,used);
        int count=used+(a==b?0:1);if(count>maxPairs)return null;
        int[] q=p.clone();q[a]=b;q[b]=a;return new State(q,count);
    }
    private void search(int[] p,int used) {
        if(cutoff || stopped)return;
        if(Thread.currentThread().isInterrupted() || (cancelled!=null && cancelled.getAsBoolean())){stopped=true;return;}
        if(nodes>=nodeLimit || answers.size()>=solutionLimit){cutoff=true;return;}
        nodes++;
        if(!seen.add(Arrays.toString(p)))return;
        boolean changed;
        do {
            changed=false;
            for(int[] e:edges) {
                int i=e[0],a=e[1],b=e[2];
                if(p[a]!=-1) {
                    State q=extend(p,used,b,rows[i][p[a]]);if(q==null)return;
                    changed|=!Arrays.equals(q.board,p);p=q.board;used=q.used;
                }
                if(p[b]!=-1) {
                    State q=extend(p,used,a,rows[i][p[b]]);if(q==null)return;
                    changed|=!Arrays.equals(q.board,p);p=q.board;used=q.used;
                }
            }
        }while(changed);
        List<State> options=null;
        for(int[] e:edges) {
            int i=e[0],a=e[1],b=e[2];
            if(p[a]!=-1 && p[b]!=-1)continue;
            List<State> values=new ArrayList<>();
            for(int x=0;x<26;x++) {
                State q=extend(p,used,a,x);
                if(q!=null)q=extend(q.board,q.used,b,rows[i][x]);
                if(q!=null)values.add(q);
            }
            if(values.isEmpty())return;
            if(options==null || values.size()<options.size())options=values;
        }
        if(options==null) {
            for(int[] answer:answers)if(Arrays.equals(answer,p))return;
            answers.add(p.clone());return;
        }
        for(State q:options)search(q.board,q.used);
    }
}
