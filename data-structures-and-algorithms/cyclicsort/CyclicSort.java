package cyclicsort;
import utils.ArrayUtils;
public class CyclicSort {

    public static void main(String[] args) {

        int[] arr = {1, 2, 5, 3, 4};

        sort(arr);

        System.out.println(java.util.Arrays.toString(arr));
    }

    // Cyclic sort
    static void sort(int[] arr) {

        int index = 0;

        while (index < arr.length) {

            int correct = arr[index] - 1;

            if (arr[index] != arr[correct]) {
                ArrayUtils.swap(arr, index, correct);
            } else {
                index++;
            }
        }
    }
}