package cyclicsort;
import java.util.Arrays;

public class SetMismatch {

    public static void main(String[] args) {

        int[] arr = {1, 2, 2, 4};

        System.out.println(Arrays.toString(find(arr)));
    }

    // Finds duplicate and missing numbers
    static int[] find(int[] arr) {

        CyclicSort.sort(arr);

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] != i + 1) {
                return new int[]{arr[i], i + 1};
            }
        }

        return new int[]{-1, -1};
    }
}