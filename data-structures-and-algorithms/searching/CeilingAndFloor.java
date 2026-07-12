package searching;
public class CeilingAndFloor {

    public static void main(String[] args) {

        int[] arr = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 55, 69, 74, 85, 92, 99};
        char[] letters = {'a', 'b', 'f', 'm', 'p'};

        System.out.println(findCeiling(arr, 75));
        System.out.println(nextGreatestLetter(letters, 'a'));
    }

    // Finds the ceiling of a number
    static int findCeiling(int[] arr, int target) {

        int start = 0;
        int end = arr.length - 1;

        while (start <= end) {

            int mid = start + (end - start) / 2;

            if (arr[mid] == target) {
                return arr[mid];
            }

            if (target < arr[mid]) {
                end = mid - 1;
            } else {
                start = mid + 1;
            }
        }

        return start < arr.length ? arr[start] : -1;
    }

    // Finds the next greatest letter
    static char nextGreatestLetter(char[] letters, char target) {

        int start = 0;
        int end = letters.length - 1;

        while (start <= end) {

            int mid = start + (end - start) / 2;

            if (target < letters[mid]) {
                end = mid - 1;
            } else {
                start = mid + 1;
            }
        }

        return letters[start % letters.length];
    }
}