package searching;
public class RotatedArray {

    public static void main(String[] args) {

        int[] arr = {7, 8, 9, 1, 3, 4, 5, 6};

        System.out.println(search(arr, 1));
    }

    // Searches in a rotated sorted array
    static int search(int[] arr, int target) {

        int pivot = findPivot(arr);

        if (pivot == -1) {
            return BinarySearch.search(arr, target, 0, arr.length - 1);
        }

        if (arr[pivot] == target) {
            return pivot;
        }

        if (target >= arr[0]) {
            return BinarySearch.search(arr, target, 0, pivot - 1);
        }

        return BinarySearch.search(arr, target, pivot + 1, arr.length - 1);
    }

    // Finds the pivot index
    static int findPivot(int[] arr) {

        int start = 0;
        int end = arr.length - 1;

        while (start <= end) {

            int mid = start + (end - start) / 2;

            if (mid < end && arr[mid] > arr[mid + 1]) {
                return mid;
            }

            if (mid > start && arr[mid] < arr[mid - 1]) {
                return mid - 1;
            }

            if (arr[mid] <= arr[start]) {
                end = mid - 1;
            } else {
                start = mid + 1;
            }
        }

        return -1;
    }
}