package cyclicsort;
import utils.ArrayUtils;
public class FirstMissingPositive {

    public static void main(String[] args) {

        int[] arr = {3, 4, -1, 1};

        System.out.println(find(arr));
    }

    // Finds the first missing positive
    static int find(int[] arr) {

        int index = 0;

        while (index < arr.length) {

            if (arr[index] > 0
                    && arr[index] <= arr.length
                    && arr[index] != arr[arr[index] - 1]) {

                ArrayUtils.swap(arr, index, arr[index] - 1);

            } else {
                index++;
            }
        }

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] != i + 1) {
                return i + 1;
            }
        }

        return arr.length + 1;
    }
}