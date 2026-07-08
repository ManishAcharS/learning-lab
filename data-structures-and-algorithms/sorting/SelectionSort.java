package sorting;
import utils.ArrayUtils;
public class SelectionSort {

    public static void main(String[] args) {

        int[] arr = {1, 2, 5, 3, 4};

        sort(arr);

        System.out.println(java.util.Arrays.toString(arr));
    }

    // Selection sort
    static void sort(int[] arr) {

        int last = arr.length - 1;

        for (int i = 0; i <= last; i++) {

            int maxIndex = findMax(arr, last - i);

            ArrayUtils.swap(arr, maxIndex, last - i);
        }
    }

    // Finds the max element index
    static int findMax(int[] arr, int end) {

        int max = 0;

        for (int i = 0; i <= end; i++) {

            if (arr[i] > arr[max]) {
                max = i;
            }
        }

        return max;
    }
}