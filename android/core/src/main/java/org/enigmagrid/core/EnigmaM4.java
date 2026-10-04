package org.enigmagrid.core;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** CPU reference primitive. No Android dependencies or mutable shared key state. */
public final class EnigmaM4 {
    private static final Map<String, int[]> FORWARD = new HashMap<>();
    private static final Map<String, int[]> REVERSE = new HashMap<>();
    private static final Map<String, String> NOTCHES = new HashMap<>();
    static {
        String[] names = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "Beta", "Gamma", "Bthin", "Cthin"};
        String[] wires = {
            "EKMFLGDQVZNTOWYHXUSPAIBRCJ", "AJDKSIRUXBLHWTMCQGZNPYFVOE",
            "BDFHJLCPRTXVZNYEIWGAKMUSQO", "ESOVPZJAYQUIRHXLNFTGKDCMWB",
            "VZBRGITYUPSDNHLXAWMJQOFECK", "JPGVOUMFYQBENHZRDKASXLICTW",
            "NZJHGRCXMYSWBOUFAIVLPEKQDT", "FKQHTLXOCBJSPDZRAMEWNIUYGV",
            "LEYJVCNIXWPBQMDRTAKZGFUHOS", "FSOKANUERHMBTIYCWLQPZXVGJD",
            "ENKQAUYWJICOPBLMDXZVFTHRGS", "RDOBJNTKVEHMLFCWZAXGYIPSUQ"};
        String[] notches = {"Q", "E", "V", "J", "Z", "ZM", "ZM", "ZM"};
        for (int i = 0; i < names.length; i++) {
            int[] f = new int[26], b = new int[26];
            for (int j = 0; j < 26; j++) { f[j] = wires[i].charAt(j) - 'A'; b[f[j]] = j; }
            FORWARD.put(names[i], f); REVERSE.put(names[i], b);
            if (i < 8) NOTCHES.put(names[i], notches[i]);
        }
    }
    private EnigmaM4() {}
    /** Packed Vulkan row inputs; mechanical stepping stays shared with the reference. */
    public static int[] rowInputs(String reflector,String greek,String[] moving,String positions,String rings,int offset,int length) {
        if(offset<0||length<1||offset+length>72)throw new IllegalArgumentException("Invalid row interval");
        // Reuse strict key validation before table lookup.
        crypt("A",reflector,greek,moving,positions,rings,new String[0]);
        String[] names={"I","II","III","IV","V","VI","VII","VIII","Beta","Gamma","Bthin","Cthin"};
        java.util.List<String> ids=java.util.Arrays.asList(names);
        int[] result=new int[625+length*9];result[0]=length;
        for(int i=0;i<12;i++)for(int x=0;x<26;x++){result[1+i*26+x]=FORWARD.get(names[i])[x];result[313+i*26+x]=REVERSE.get(names[i])[x];}
        int[] p=letters(positions,4),r=letters(rings,4);
        String[] rotors={greek,moving[0],moving[1],moving[2]};
        for(int slot=0;slot<offset+length;slot++) {
            boolean middle=NOTCHES.get(moving[1]).indexOf('A'+p[2])>=0;
            boolean right=NOTCHES.get(moving[2]).indexOf('A'+p[3])>=0;
            if(middle)p[1]=mod(p[1]+1);if(middle||right)p[2]=mod(p[2]+1);p[3]=mod(p[3]+1);
            if(slot<offset)continue;
            int base=625+(slot-offset)*9;
            for(int j=0;j<4;j++){result[base+j]=ids.indexOf(rotors[j]);result[base+5+j]=mod(p[j]-r[j]);}
            result[base+4]=ids.indexOf(reflector);
        }
        return result;
    }
    /** Evaluate all contacts after stepping once per position, without 26 full decryptions. */
    public static int[][] rows(String reflector,String greek,String[] moving,String positions,String rings,int offset,int length) {
        int[] packed=rowInputs(reflector,greek,moving,positions,rings,offset,length);
        int[][] result=new int[length][26];
        for(int slot=0;slot<length;slot++) {
            int base=625+slot*9;
            for(int contact=0;contact<26;contact++) {
                int x=contact;
                for(int j=3;j>=0;j--){int shift=packed[base+5+j];x=mod(packed[1+packed[base+j]*26+mod(x+shift)]-shift);}
                x=packed[1+packed[base+4]*26+x];
                for(int j=0;j<4;j++){int shift=packed[base+5+j];x=mod(packed[313+packed[base+j]*26+mod(x+shift)]-shift);}
                result[slot][contact]=x;
            }
        }
        return result;
    }
    private static int mod(int n) { return (n % 26 + 26) % 26; }
    private static int pass(int x, int[] wiring, int p, int r) {
        return mod(wiring[mod(x + p - r)] - p + r);
    }
    private static int[] letters(String value, int length) {
        if (value == null || value.length() != length) throw new IllegalArgumentException("Invalid length");
        int[] out = new int[length];
        for (int i = 0; i < length; i++) {
            char c = value.charAt(i);
            if (c < 'A' || c > 'Z') throw new IllegalArgumentException("Expected A-Z");
            out[i] = c - 'A';
        }
        return out;
    }
    public static String crypt(String text, String reflector, String greek,
            String[] moving, String positions, String rings, String[] pairs) {
        if (!("Bthin".equals(reflector) || "Cthin".equals(reflector))) throw new IllegalArgumentException("Reflector");
        if (!("Beta".equals(greek) || "Gamma".equals(greek))) throw new IllegalArgumentException("Greek rotor");
        if (moving == null || moving.length != 3) throw new IllegalArgumentException("Moving rotors");
        Set<String> used = new HashSet<>();
        for (String rotor : moving) if (!NOTCHES.containsKey(rotor) || !used.add(rotor)) throw new IllegalArgumentException("Moving rotors");
        int[] p = letters(positions, 4), r = letters(rings, 4);
        int[] input = letters(text, text.length()), plug = new int[26];
        boolean[] connected = new boolean[26];
        for (int i = 0; i < 26; i++) plug[i] = i;
        if (pairs == null || pairs.length > 13) throw new IllegalArgumentException("Plugboard");
        for (String pair : pairs) {
            int[] ab = letters(pair, 2); int a = ab[0], b = ab[1];
            if (a == b || connected[a] || connected[b]) throw new IllegalArgumentException("Overlapping plugboard");
            connected[a] = connected[b] = true; plug[a] = b; plug[b] = a;
        }
        String[] rotors = {greek, moving[0], moving[1], moving[2]};
        StringBuilder output = new StringBuilder(input.length);
        for (int letter : input) {
            boolean middle = NOTCHES.get(moving[1]).indexOf('A' + p[2]) >= 0;
            boolean right = NOTCHES.get(moving[2]).indexOf('A' + p[3]) >= 0;
            if (middle) p[1] = mod(p[1] + 1);
            if (middle || right) p[2] = mod(p[2] + 1);
            p[3] = mod(p[3] + 1);
            int x = plug[letter];
            for (int i = 3; i >= 0; i--) x = pass(x, FORWARD.get(rotors[i]), p[i], r[i]);
            x = FORWARD.get(reflector)[x];
            for (int i = 0; i < 4; i++) x = pass(x, REVERSE.get(rotors[i]), p[i], r[i]);
            output.append((char) ('A' + plug[x]));
        }
        return output.toString();
    }
}
