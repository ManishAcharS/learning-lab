package strings;
public class Palindrome {

    public static void main(String[] args) {

        String word = "madama";

        System.out.println(isPalindrome(word));
    }

    // Checks if a string is a palindrome
    static boolean isPalindrome(String word) {

        String str = word.toLowerCase();

        for (int i = 0; i < str.length() / 2; i++) {

            if (str.charAt(i) != str.charAt(str.length() - 1 - i)) {
                return false;
            }
        }

        return true;
    }
}