import org.enigmagrid.core.EnigmaM4;
import java.io.BufferedReader;
import java.io.InputStreamReader;

/** Line protocol used only by the cross-language qualification test. */
public final class ReferenceCli {
    public static void main(String[] args) throws Exception {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
        String line;
        while ((line = input.readLine()) != null) {
            String[] f = line.split("\\|", -1);
            try {
                System.out.println(EnigmaM4.crypt(f[0], f[1], f[2], f[3].split(","),
                    f[4], f[5], f[6].isEmpty() ? new String[0] : f[6].split(",")));
            } catch (IllegalArgumentException e) { System.out.println("INVALID"); }
        }
    }
}
