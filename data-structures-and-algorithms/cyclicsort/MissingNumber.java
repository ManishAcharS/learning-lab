package cyclicsort;
import utils.ArrayUtils;
public class MissingNumber {

    public static void main(String[] args) {

        int[] arr = {4, 0, 2, 1};

        System.out.println(find(arr));
    }

    // Finds the missing number
    static int find(int[] arr) {

        int index = 0;

        while (index < arr.length) {

            if (arr[index] < arr.length && arr[index] != arr[arr[index]]) {
                ArrayUtils.swap(arr, index, arr[index]);
            } else {
                index++;
            }
        }

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] != i) {
                return i;
            }
        }

        return arr.length;
    }
}