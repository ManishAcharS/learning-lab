# 1929. Concatenation of Array
from typing import List


class Solution:
    def getConcatenation(self, nums: List[int]) -> List[int]:
        ans = nums + nums
        return ans

ls = [n for n in range(1, 4)]
print(Solution.getConcatenation(ls))