package searching;
public class LinearSearch {

    public static void main(String[] args) {

        int[] arr = {1, 5, 6, 4, 2, 3, 8, 2, 9, 0};

        System.out.println(contains(arr, 5));
        System.out.println(firstOccurrence(arr, 2));
        System.out.println(countOccurrences(arr, 2));
        System.out.println(lastOccurrence(arr, 2));
    }

    // Checks if an element exists
    static boolean contains(int[] arr, int target) {

        for (int num : arr) {

            if (num == target) {
                return true;
            }
        }

        return false;
    }

    // Finds the first occurrence
    static int firstOccurrence(int[] arr, int target) {

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] == target) {
                return i;
            }
        }

        return -1;
    }

    // Counts total occurrences
    static int countOccurrences(int[] arr, int target) {

        int count = 0;

        for (int num : arr) {

            if (num == target) {
                count++;
            }
        }

        return count;
    }

    // Finds the last occurrence
    static int lastOccurrence(int[] arr, int target) {

        int lastIndex = -1;

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] == target) {
                lastIndex = i;
            }
        }

        return lastIndex;
    }
}