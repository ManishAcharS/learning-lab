package sorting;
import utils.ArrayUtils;
public class InsertionSort {

    public static void main(String[] args) {

        int[] arr = {1, 2, 5, 3, 4};

        sort(arr);

        System.out.println(java.util.Arrays.toString(arr));
    }

    // Insertion sort
    static void sort(int[] arr) {

        for (int i = 0; i < arr.length - 1; i++) {

            for (int j = i + 1; j > 0; j--) {

                if (arr[j - 1] > arr[j]) {
                    ArrayUtils.swap(arr, j - 1, j);
                } else {
                    break;
                }
            }
        }
    }
}