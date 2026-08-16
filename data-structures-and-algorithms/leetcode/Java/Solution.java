// 1929. Concatenation of Array
class Solution {
    public int[] getConcatenation(int[] nums) {
        int n = nums.length;
        int[] ans = new int[2 * n];
        
        for (int i = 0; i < n; i++) {
            ans[i] = nums[i];     // Fills the first half
            ans[i + n] = nums[i]; // Fills the second half
        }
        
        return ans;
    }
}