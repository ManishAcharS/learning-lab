package sorting;
import utils.ArrayUtils;
public class BubbleSort {

    public static void main(String[] args) {

        int[] arr = {1, 2, 5, 3, 4};

        sort(arr);

        System.out.println(java.util.Arrays.toString(arr));
    }

    // Bubble sort
    static void sort(int[] arr) {

        for (int i = 0; i < arr.length; i++) {

            boolean swapped = false;

            for (int j = 1; j < arr.length - i; j++) {

                if (arr[j - 1] > arr[j]) {

                    ArrayUtils.swap(arr, j - 1, j);
                    swapped = true;
                }
            }

            if (!swapped) {
                break;
            }
        }
    }
}