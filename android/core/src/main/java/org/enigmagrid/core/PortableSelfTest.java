package org.enigmagrid.core;

/** Small startup arithmetic check against independent NumPy/Numba goldens.
 * Covers 256 initial keys and one scored mutation/acceptance step for each C3
 * pair range. Does not replace full-unit release qualification or verification.
 */
public final class PortableSelfTest {
    private PortableSelfTest() {}
    private static final String[][] GOLD = {
        {"121416849826178189842829416578566957609", "54424835272139916671769879696161322297",
         "b6c7d7d48eff808ac5a9a1ea1e3f6aade697e9e3d3da4475bc2d8cee282c15ba",
         "e2dfb4feb26ad17cd16a8262734ad1f6cd536151b2629a1892732c7763109363"},
        {"208321120469391775965813620669216293656", "331920061597555133829835660021216857471",
         "88d742bc17a94f3392f3b4575b7362cb35d17ab6b90705a5a431b3c6b03a1932",
         "51e228f060732cf619ed84ca5ba928b72cd496cf77e7cba2010c18343ad10011"},
        {"249061168319703759842642776670997606355", "104985754787501430379085379746086941559",
         "612d5ef54a1065440bc6927630aeba19bf8665208a56f1a1d9c661f4d5e95d79",
         "4fe0073039461b4bddc3c1a4bd718345657f70a2b08aad67ae46b23e7923fd82"}
    };
    public static void verify(int[] cipher, int[] quadgrams) throws Exception {
        int[][] pairs={{0,3},{4,10},{11,13}};
        for(int i=0;i<GOLD.length;i++) {
            PortableKeySampler sampler=new PortableKeySampler(
                new PortablePcg64(GOLD[i][0],GOLD[i][1]),pairs[i][0],pairs[i][1],
                new int[]{1,2,3,4,5,6});
            String[] actual=PortableSearchPrefix.simulate(cipher,quadgrams,sampler,512,1);
            if(!GOLD[i][2].equals(actual[0])||!GOLD[i][3].equals(actual[1]))
                throw new IllegalStateException("Portable arithmetic qualification failed: profile "+i);
        }
    }
}
