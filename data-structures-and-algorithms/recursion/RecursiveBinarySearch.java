package recursion;
public class RecursiveBinarySearch {

    public static void main(String[] args) {

        int[] arr = {1, 4, 7, 10, 15, 18, 22, 30, 35, 40};

        int index = search(arr, 1, 0, arr.length - 1);

        System.out.println(arr[index]);
    }

    // Performs binary search recursively
    static int search(int[] arr, int target, int start, int end) {

        if (start > end) {
            return -1;
        }

        int mid = start + (end - start) / 2;

        if (arr[mid] == target) {
            return mid;
        }

        if (target < arr[mid]) {
            return search(arr, target, start, mid - 1);
        }

        return search(arr, target, mid + 1, end);
    }
}