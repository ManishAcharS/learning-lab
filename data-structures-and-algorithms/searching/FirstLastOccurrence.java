package searching;
import java.util.Arrays;

public class FirstLastOccurrence {

    public static void main(String[] args) {

        int[] arr = {1, 2, 3, 3, 3, 5, 6};

        System.out.println(Arrays.toString(findRange(arr, 3)));
    }

    // Returns first and last occurrence
    static int[] findRange(int[] arr, int target) {

        return new int[]{
                findOccurrence(arr, target, true),
                findOccurrence(arr, target, false)
        };
    }

    // Finds first or last occurrence
    static int findOccurrence(int[] arr, int target, boolean first) {

        int start = 0;
        int end = arr.length - 1;
        int answer = -1;

        while (start <= end) {

            int mid = start + (end - start) / 2;

            if (arr[mid] == target) {

                answer = mid;

                if (first) {
                    end = mid - 1;
                } else {
                    start = mid + 1;
                }

            } else if (target < arr[mid]) {
                end = mid - 1;
            } else {
                start = mid + 1;
            }
        }

        return answer;
    }
}