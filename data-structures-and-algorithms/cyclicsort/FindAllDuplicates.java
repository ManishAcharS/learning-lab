package cyclicsort;
import java.util.ArrayList;
import java.util.List;

public class FindAllDuplicates {

    public static void main(String[] args) {

        int[] arr = {4, 3, 2, 7, 8, 2, 3, 1};

        System.out.println(find(arr));
    }

    // Finds all duplicates
    static List<Integer> find(int[] arr) {

        CyclicSort.sort(arr);

        List<Integer> answer = new ArrayList<>();

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] != i + 1) {
                answer.add(arr[i]);
            }
        }

        return answer;
    }
}