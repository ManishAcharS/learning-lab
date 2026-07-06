package searching;
public class InfiniteArray {

    public static void main(String[] args) {

        int[] arr = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 55, 69, 74, 85, 92, 99};

        System.out.println(search(arr, 5));
    }

    // Searches in an infinite sorted array
    static int search(int[] arr, int target) {

        int start = 0;
        int end = 1;

        while (end < arr.length && target > arr[end]) {

            int newStart = end + 1;

            end = end + (end - start + 1) * 2;

            if (end >= arr.length) {
                end = arr.length - 1;
            }

            start = newStart;
        }

        return BinarySearch.search(arr, target, start, end);
    }
}