package org.enigmagrid.core;

import java.math.BigInteger;
import java.util.*;
import static org.enigmagrid.core.Canonical.*;

/** Indexed program expansion, identical to constrained_program_v1. */
public final class ResearchProgram {
    private static final BigInteger DOMAIN=BigInteger.valueOf(BoundedCrib.DOMAIN);
    public static final class Hypothesis implements Comparable<Hypothesis> {
        public final String text; public final int offset;
        public Hypothesis(String text,int offset) {
            if(text==null||!text.matches("[A-Z]{1,72}")||offset<0||offset>72-text.length())throw new IllegalArgumentException("Invalid hypothesis");
            this.text=text;this.offset=offset;
        }
        @Override public int compareTo(Hypothesis other){int c=text.compareTo(other.text);return c==0?Integer.compare(offset,other.offset):c;}
    }
    public static List<Long> coreIndices(String identity,long start,int count) {
        if(start<0||count<1||count>128||start>BoundedCrib.DOMAIN-count)throw new IllegalArgumentException("Invalid range");
        BigInteger raw=new BigInteger(sha256(identity),16);
        BigInteger stride=raw.divide(DOMAIN).mod(DOMAIN);
        if(stride.signum()==0)stride=BigInteger.ONE;
        while(!stride.gcd(DOMAIN).equals(BigInteger.ONE))stride=stride.add(BigInteger.ONE);
        BigInteger shift=raw.mod(DOMAIN);List<Long> out=new ArrayList<>();
        for(long i=start;i<start+count;i++)out.add(shift.add(stride.multiply(BigInteger.valueOf(i))).mod(DOMAIN).longValueExact());
        return out;
    }
    public static Map<String,Object> jobAt(String cipher,List<Hypothesis> hypotheses,long ordinal,int chunk,int candidateLimit) {
        if(cipher==null||!cipher.matches("[A-Z]{1,72}")||ordinal<0||chunk<1||chunk>128||candidateLimit<1||candidateLimit>32||hypotheses==null||hypotheses.isEmpty()||hypotheses.size()>9216)throw new IllegalArgumentException("Invalid program");
        List<Hypothesis> rows=new ArrayList<>(new TreeSet<>(hypotheses));
        long wave=ordinal/rows.size();
        if(wave>(BoundedCrib.DOMAIN-1)/chunk)throw new IllegalArgumentException("Program exhausted");
        long start=wave*chunk;Hypothesis h=rows.get((int)(ordinal%rows.size()));
        if(h.offset+h.text.length()>cipher.length())throw new IllegalArgumentException("Crib outside ciphertext");
        String identity=digest(object("version","constrained_program_v1","ciphertext",cipher,"crib",h.text,"offset",h.offset,"pairs",10));
        Map<String,Object> job=object("engine","bounded_crib_v1","ciphertext",cipher,"crib",h.text,"offset",h.offset,"core_indices",coreIndices(identity,start,(int)Math.min(chunk,BoundedCrib.DOMAIN-start)),"model","clean","pairs",10,"budgets",object("node_limit",5000,"board_limit",64,"completion_limit",256,"candidate_limit",candidateLimit));
        String id=digest(job);job.put("id",id);job.put("program","constrained_program_v1");job.put("ordinal",ordinal);return job;
    }
}
